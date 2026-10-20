---
phase: 19-execution-plan-binding-price-check
plan: 17
subsystem: gate
tags: [phase-gate, glossary, owner-gaps, hand-off-notes, secret-posture, tdd]
requires: ["19-01", "19-02", "19-03", "19-04", "19-05", "19-06", "19-07", "19-08", "19-09", "19-10", "19-11", "19-12", "19-13", "19-14", "19-15", "19-16"]
provides:
  - "tests/test_phase19_gate.py: artifact, symbol and requirement-test presence, nine machine-checked invariants, GLOSSARY 9.3/9.4 checks, owner-gap register checks, EXEC-07 note check, ROADMAP criteria check, hand-off notes check"
  - "tests/test_execution_secret_posture.py: the secret-posture scan extended over the new execution modules"
  - "docs/GLOSSARY.md: section 9.3 and 9.4 rows for the Phase 19 plain reason codes and SAFE_MODE reasons"
  - ".planning/phases/19-execution-plan-binding-price-check/19-OWNER-GAPS.md: the owner-gap register"
affects: [phase-20, phase-21, phase-22, phase-23, phase-24]
actuals:
  commits: 4
  tasks: 3
  tokens: not measured (the executor was stopped by the owner before its final report)
status: complete-pending-owner-read
commits: 4
plan_head_before: 02c1b3c
plan_head_after: ba31e72
key-files:
  created: [tests/test_phase19_gate.py, .planning/phases/19-execution-plan-binding-price-check/19-OWNER-GAPS.md]
  modified: [docs/GLOSSARY.md, tests/test_execution_secret_posture.py, tests/test_phase18_gate.py, tests/test_intent_recovery_pg.py, tests/test_realized_risk_persistence_pg.py, .planning/REQUIREMENTS.md, .planning/phases/18-user-data-stream-error-taxonomy/18-TRACEABILITY.md]
requirements-completed: []
---

# Phase 19 Plan 17: Phase gate, GLOSSARY rows and the owner-gap register Summary

The phase now has a machine-checked gate, its new strings are documented where operators look for them, and every item the phase did not and must not decide is in one register. No requirement is marked complete here: EXEC-01, EXEC-02, RISK-04, APRV-01, APRV-02 and EXEC-07 stay Pending because nothing has run against a real process or Binance Demo (O-01 stays open).

## What was built

1. **Gate tests (Task 1, `a8d6507`).** `tests/test_phase19_gate.py`, modelled on `tests/test_phase18_gate.py`: the Phase 19 artifacts exist; the public symbols and adapter methods import; every requirement-named test exists; nine invariants hold: (1) the pure modules import no SDK, float or clock, (2) the pinned enums and role codes are unchanged, (3) `execute_approved_plan` places no protective order, (4) the execution limits file has no placeholder and no invented number, (5) the ratified Binance limits file is unchanged, (6) the frozen protective sizing is unchanged, (7) no execution module imports the backtest, (8) D055 stays open and the Phase 18 gate is green, (9) every requirement name is a known one. `tests/test_execution_secret_posture.py` now also scans the new modules (`binding`, `emergency_close`, `execution_limits`, `live_context`, `lot_split`, `pre_placement`, `protection`, `tp_sizing`).
2. **GLOSSARY (Task 2, `a0fa3a3`).** One row per new plain-string code in 9.3 with the emitting module and the status "proposed canonical, promote in Phase 20" (protection codes) or "promote in Phase 24" (binding and pre-placement codes); `PLAN_INVALIDATED_BEFORE_PLACEMENT` is marked distinct from `INVALIDATED`; the new SAFE_MODE reasons are in 9.4; the pinned `RejectionReason` enum and 9.1 are untouched (tests assert it).
3. **Owner-gap register and EXEC-07 note (Task 3, `aa51f0b`).** `19-OWNER-GAPS.md` has six sections: decisions the owner still owns (O-01 to O-05, Q3, Q4, Q5 with its decided state and the open Phase 20 closing rule, the Phase 18 skipped review items, the partial-fill question), the 11 Demo probes verbatim, assumptions A1 to A10, known consequences, documentation that waits for D055 acceptance, and network gaps. The EXEC-07 line in `REQUIREMENTS.md` carries the Phase 19 note and stays Pending. Gate tests assert each identifier is present, that nothing is presented as solved, that the ROADMAP success criteria of Phases 19 and 20 are unchanged, and that the hand-off notes of Phases 20 to 24 exist and are pointed at by `Input:` lines.
4. **Legacy tests found by the full suite (`ba31e72`).** Five PostgreSQL tests of plans 17-12 and 19-06 still assumed an entry-time stop: `tests/test_intent_recovery_pg.py` (crash steps now only the ENTRY steps from the manager; the STOP_LOSS write-ahead steps are crashed through coordinator-style writes) and `tests/test_realized_risk_persistence_pg.py` (the manager no longer writes a STOP_LOSS intent; the test asserts the entry carries the figure and no protective intent exists). `tests/test_phase18_gate.py` pins two renamed tests (19-15 and 19-16 rewrites).

## Deviations from Plan

1. **Task 4 (not in the plan): five legacy PG tests rewritten.** They failed only under the full suite because they were outside the files each earlier plan touched. They are the same class of legacy assertion as the 19-15 and 19-16 inventories. Judgement: fixed here, inside the gate plan, because the gate must be green.
2. **The plan was edited on 2026-10-20 before execution** (Q5 decided by the owner, new known consequences, ROADMAP check replaced by a criteria-unchanged test, hand-off notes test); the executor followed the edited plan.
3. **The executor was stopped by the owner** while starting a second full-suite run, after repeated full-suite runs. This SUMMARY was written afterwards by the orchestrator from the four commits and a re-run of the plan's own tests.
4. **`_place_protective_leg` was not removed.** `tests/test_algo_status.py` pins it and it has no caller in `src` (19-16 deviation 3). Left as a follow-up; no test or code of this plan depends on it.

## Not in this plan (recorded for the owner)

- **Probe 1 has no case in `scripts/demo_probe.py`.** The script has `closeposition_stop_flat` only; nothing places `closePosition` with a position open, which is the evidence needed for assumption A6 and for closing D055. The register lists the 11 probes but writing the cases is not a Phase 19 plan. A quick task is planned (case `closeposition_stop_open`, offline fake tests only, no `--execute`).
- **D055 wording.** `19-DEC-D055-DRAFT.md`, `19-CONTEXT.md` and the register still say "closure". The owner's reviewer asked for: D-10 selected, D055 OPEN pending Probe 1, LIVE blocked, with each statement tagged [DOC], [DEMO] or [DESIGN]. Decision ids D079 (D-10) and D080 (Q5) are provisional and assigned when the rows are written (renumbered 2026-10-20: D077 is the stop-lost row of 19-REVIEW WR-04; renumbered again the same day: D078 is the approved-quantity row of 19-REVIEW WR-01). Pending edit.
- **Coordinator not running and no stop supervision after PROTECTED** are [DESIGN] gaps (Phases 20 and 24 notes); nothing here claims continuous protection.
- **The `<human-check>`** of Task 3 is open: the owner reads `19-OWNER-GAPS.md` and confirms every open item is listed and none is presented as solved.

## Verification (real runs, worktree branch p19-15)

- `uv run pytest -m "not docker"` on `tests/test_phase19_gate.py tests/test_execution_secret_posture.py tests/test_phase18_gate.py tests/test_decision_alignment_bookkeeping.py tests/test_domain_enums.py tests/test_intent_recovery_pg.py tests/test_realized_risk_persistence_pg.py`: all passed, no skips (TEST_DATABASE_URL set, PG tests ran).
- `scripts/verify_decision_alignment.py glossary` and `reqs`: ALL_PASS.
- `uv run ruff check`: passed. `uv run ruff format --check`: 660 files already formatted. `uv run mypy src`: no issues in 212 files.
- The whole suite has NOT been run on the final commit of this plan (the executor's full-suite runs found the five PG tests; its last run was stopped). It is to be run once on the merged result before anything reaches `develop`.
