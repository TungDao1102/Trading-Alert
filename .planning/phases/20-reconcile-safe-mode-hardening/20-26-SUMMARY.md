---
phase: 20-reconcile-safe-mode-hardening
plan: 26
subsystem: docs
tags: [documentation-alignment, d077, owner-decision-o-a, criterion-2, risk-03, ops-05, gate-pin]
status: complete

requires:
  - phase: 20-reconcile-safe-mode-hardening
    provides: "20-24 documentation of what Phase 20 built; 20-17 operator controls (close, protect delegation)"
provides:
  - "ROADMAP Phase 20 criterion 2 and checklist line, REQUIREMENTS RISK-03 and OPS-05 note in the owner-accepted wording"
  - "EXECUTION_SPEC section 9 and 10.1, SECURITY_AND_OPERATIONS section 7, RISK_MANAGEMENT, RUNBOOK section 3 aligned with D077 and the four re-placement cases"
  - "tests/test_phase19_gate.py::test_phase20_criteria_match_the_owner_accepted_wording (pins the ROADMAP Phase 20 criteria to the ACCEPTED-CRITERIA block)"
affects: [20-DEFERRED (no B2/B3-reject row, the owner confirmed), phase 24 composition, phase 21 (DAILY_STOP producers)]

requirements-addressed: [RISK-03, OPS-05]

actuals:
  tokens: 40000
  tasks: 3
  commits: 3
plan_head_before: 85ecaa331270b4bc752341c69c6343544c487e69
plan_head_after: 720dc32fd58b677a49ce33f315214ff57e6102f6

key-files:
  modified:
    - .planning/ROADMAP.md
    - .planning/REQUIREMENTS.md
    - docs/trading/EXECUTION_SPEC.md
    - docs/operations/SECURITY_AND_OPERATIONS.md
    - docs/trading/RISK_MANAGEMENT.md
    - docs/operations/RUNBOOK.md
    - docs/DOC_STATUS.md
    - tests/test_phase19_gate.py
    - scripts/decision_alignment/ops_risk.py
  created:
    - .planning/phases/20-reconcile-safe-mode-hardening/20-PROPOSED-WORDING.md

key-decisions:
  - "Owner decision O-A recorded verbatim below: wording accepted as proposed, B2/B3 confirmed."
  - "No text beyond the accepted text was written (no -2013 caveat, no extra sentence)."
---

# Phase 20 Plan 26: Owner-accepted re-placement wording Summary

Criterion 2, RISK-03, the canonical docs and the generic re-placement claims now state the four D077-aligned cases exactly as the owner accepted them, and a gate test pins the accepted Phase 20 criteria; no requirement status, checkbox or DECISIONS row changed.

## Owner decision O-A

approved
B2/B3: confirm

(Typed by the owner in the orchestrating session on 2026-10-22 and relayed verbatim by the orchestrator. Task 2 checkpoint answered; the wording of Places 1 to 6 and the other generic claims is accepted as proposed, without changes; the never-confirmed same-id re-place is accepted policy; the owner added no condition.)

This is a documentation alignment with D077 and the fill-driven model of Phase 19 (D-10). It is not a new policy decision, not D055 closure (D055 stays Accepted for the invariant and probe plan, execution model open until Probe 1), not Demo validation and not LIVE approval. Evidence label: [DOC] only; no [DEMO] claim.

## Tasks

| Task | Name | Commit | Result |
|------|------|--------|--------|
| 1 | Tracer: 20-PROPOSED-WORDING.md | 377332c2 (earlier executor, merged as a11f767e) | proposal with current/proposed text for the six places, the owner item and the generic-claims search |
| 2 | Owner verification O-A | no commit | answered: approved / B2/B3: confirm |
| 3 | Apply the accepted text, move the criteria pin | 720dc32f | see below |

## What Task 3 changed

- `.planning/ROADMAP.md` (two scoped single-line replacements, bytes-aware): the Phase 20 checklist line text after " - " (checkbox untouched) and Phase 20 criterion 2 (taken from the ACCEPTED-CRITERIA block). `git diff -U0` shows exactly those two hunks. Criteria 1, 3, 4, 5, the inherited item [D055], the Phase 11 criterion (line ~397) and the Plans list are untouched.
- `.planning/REQUIREMENTS.md`: RISK-03 text and the OPS-05 italic note (Phase 20 delivered the contract, the journal-first sender, dedupe, bounded message retry and the `OPS05_MATRIX` producers with fakes; DAILY_STOP and the daily-loss WARNING completed by Phase 21; "Stays Pending"). Both checkboxes stay `[ ]` and both traceability rows stay Pending; EXEC-06 not edited; no `requirements.mark-complete` was run.
- `docs/trading/EXECUTION_SPEC.md`: section 9 orphan paragraph and re-placement paragraph (four cases), and the section 10.1 implementation-status sentence (the "owner confirms" variant: "applies the never-confirmed rule of section 9 to it: a REST-proved absence is answered by a placement under the deterministic id at the plan stop-loss, at most once per coordinator step").
- `docs/operations/SECURITY_AND_OPERATIONS.md`: section 7 re-placement bullet and the implementation-status paragraph.
- `docs/trading/RISK_MANAGEMENT.md` line 88; `docs/operations/RUNBOOK.md` lines 42, 47, 49 (the "D034 and D077" sentence with the operator-close sentence, as proposed).
- `docs/DOC_STATUS.md`: one dated entry (2026-10-22).
- `tests/test_phase19_gate.py`: the criteria-unchanged loop covers Phase 19 only (the test keeps its old name `..._of_phases_19_and_20_are_unchanged` so existing references still resolve; a comment on `ROADMAP_CRITERIA_BASELINE` explains the narrowing), and `test_phase20_criteria_match_the_owner_accepted_wording` compares the ROADMAP Phase 20 `**Success Criteria**` block with the ACCEPTED-CRITERIA block of 20-PROPOSED-WORDING.md (CRLF-normalised, trailing whitespace stripped), skipped only when the proposal file is absent.
- Not edited (by instruction and by plan): `docs/DECISIONS.md`, `config/binance/`, `params/`, `pyproject.toml`, `uv.lock`, STATE.md, `.planning/config.json`, `.planning/state.json`, `.gsd/`, `.planning/milestone.lock`. `20-DEFERRED.md` was not touched: no B2/B3-reject row (the owner confirmed) and no rejection row.

## Deviations from Plan

**1. [Rule 3 - Blocking] Decision-alignment gate OR-01a pinned the old bullet**
- **Found during:** Task 3 (`scripts/verify_decision_alignment.py all` printed `FAIL OR-01 :: OR-01a: missing: automatically re-placed; original plan stop-loss`).
- **Issue:** `scripts/decision_alignment/ops_risk.py` `SAFE_MODE_SEC_OPS_PHRASES` required the phrases "automatically re-placed" and "original plan stop-loss" in SECURITY_AND_OPERATIONS section 7. The accepted bullet (which D077 forbids from saying "automatically re-placed" for a missing stop) does not contain them, and no sentence of my own may be added to the accepted text.
- **Fix:** replaced those two required phrases by "placed again under the same client id", "plan stop-loss" and "never re-placed", all taken from the accepted text ("never wider", "reduce-only market close", "HIGH-priority alert", "D034" stay required). `tests/test_decision_alignment_ops_risk.py` (which also uses the real file and the "never wider" removal) still passes.
- **Files modified:** `scripts/decision_alignment/ops_risk.py`.
- **Commit:** 720dc32f.

**2. [Rule 3 - Blocking] Worktree virtualenv lacked the dev extra**
- `uv run pytest` failed on `alembic`; ran `uv sync --frozen --extra dev` in the worktree. No lockfile or pyproject change.

**3. Edits to ROADMAP.md and REQUIREMENTS.md**
- The shared executor rules say not to touch these files; the plan (Task 3) and the orchestrator's explicit instruction for this run require the scoped edits. Done as scoped single-line byte-aware replacements, nothing else in either file.

Minor: the proposal file says its base was `85ecaa33`; the worktree was cut from `491db95e` (develop plus quick task 261021-sj0). Every quoted "current text" matched the file byte for byte (the script asserted exactly one match per replacement).

## Verification actually run

- `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS (before the pin change it printed the OR-01a FAIL above, which was the honest RED for deviation 1).
- `uv run pytest -m "not docker"` on tests/test_phase19_gate.py, tests/test_phase18_gate.py, tests/test_persistence_exit_evidence_pg.py, tests/test_agents_md.py, tests/test_decision_alignment_ops_risk.py, tests/test_phase20_gate.py with `TRADING_CI_STRICT=1` and `TEST_DATABASE_URL` set from the process environment: 160 passed, 0 skipped. `test_phase20_criteria_match_the_owner_accepted_wording` and `test_roadmap_success_criteria_of_phases_19_and_20_are_unchanged` both PASSED (not skipped).
- Further doc-reading tests (alerts OPS-05 matrix, all `test_decision_alignment_*`, deploy docs, drills, manual controls, emergency, soak runbook, kill-gate docs, risk portfolio/quantization, execution modes): all passed.
- `uv run mypy src`: no issues in 235 files. `uv run ruff check`: all checks passed. `uv run ruff format --check`: 727 files already formatted. `uv lock --check`: ok. `git diff --exit-code -- docs/DECISIONS.md pyproject.toml uv.lock`: exit 0.
- RED for the new test: it was written together with the ROADMAP edit and passed on first run; the pin is meaningful because the old criterion 2 text (fffdb6e) differs from the ACCEPTED-CRITERIA block, so the test would have failed before the ROADMAP edit. I did not run it in that state (no separate RED run).
- Not run: the full suite (orchestrator's job); Docker tests (Docker unavailable). Nothing is [DEMO]; no Binance or Telegram call.

## Findings for later plans

- The proposal's finding F-1 stands: at `max_unprotected_ms` the coordinator enters CLOSE_REQUIRED (SAFE_MODE, critical alert) before the closer reads the position; the accepted text states it that way. Reading the position before escalating would be a code change, not a wording change.
- `ROADMAP.md` line ~397 (Phase 11 criterion 2, "protective re-placement and a close fallback") and `REQUIREMENTS.md` EXEC-06 ("re-place protection") still carry the older generic wording; both were deliberately left alone (owner may decide).
- `docs/DECISIONS.md` D034 clause (1) still reads "automatically re-places the SL"; D077 item (4) narrows it. Untouched by design.
- The test `test_roadmap_success_criteria_of_phases_19_and_20_are_unchanged` now covers Phase 19 only but keeps its name; rename it when convenient.

## Known Stubs

None.

## Threat Flags

None (documentation, one test and a doc-gate phrase list only).

## Self-Check: PASSED

Checked: edited files present, commit 720dc32f exists on branch p20-26b, `git diff -U0` of ROADMAP shows only the two intended hunks, RISK-03 and OPS-05 lines still show `[ ]`.
