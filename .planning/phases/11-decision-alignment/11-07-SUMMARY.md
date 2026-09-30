---
phase: 11-decision-alignment
plan: 07
subsystem: authority-chain-bookkeeping
tags: [d-15, d-16, d-19, f-110, f-116, d044, d045, glossary, requirements, gate-module]
status: complete

requires:
  - phase: 11-decision-alignment
    provides: plans 11-01..11-06 (D043 row, baseline-v4 sets, universe manifest, D042 secrets control cited in SECURITY_AND_OPERATIONS, gate-module pattern in scripts/decision_alignment)
provides:
  - GLOSSARY section 9 split into 9.1 canonical codes (17 code-referenced plus reserved INSUFFICIENT_MARGIN), 9.2 five deprecated aliases, 9.3 plain-string codes, 9.4 SAFE_MODE entry reasons; new section 10 ApprovalResult
  - 13 new requirement IDs in REQUIREMENTS.md with traceability rows (phases 13-26), coverage 43/43/0, and matching ROADMAP Requirements lines
  - DECISIONS rows D044 (alignment record with ten owned follow-ups) and D045 (explicit exclusions and dispositions), DOC_STATUS change-log line, DATA_MODEL V1 status notes
  - scripts/decision_alignment/bookkeeping.py gates GL-01..GL-06, RQ-01..RQ-05, DC-01..DC-06 (17) plus 32 tests
affects: [11-08, phase-12, phase-13, phase-14, phase-17, phase-18, phase-19, phase-20, phase-22, phase-24, phase-26]

# Registered here, implemented by phases 13-26: deliberately none of the 13 new IDs is completed.
requirements-completed: []

actuals:
  tokens: 60000
  tasks: 3
  commits: 4
plan_head_before: 65dba69d302e1d45d5058dafb75578953dd9efdd
plan_head_after: 63b86706a074882ac376fedbefe62098f73c28ab

tech-stack:
  added: []
  patterns:
    - "Code-derived doc gate: GL-02 scans src/ for RejectionReason.X and requires each hit in GLOSSARY 9.1, so the glossary cannot drift from emitting code"

key-files:
  created:
    - scripts/decision_alignment/bookkeeping.py
    - tests/test_decision_alignment_bookkeeping.py
  modified:
    - docs/GLOSSARY.md
    - .planning/REQUIREMENTS.md
    - .planning/ROADMAP.md
    - docs/DECISIONS.md
    - docs/DOC_STATUS.md
    - docs/data/DATA_MODEL.md

key-decisions:
  - "No RejectionReason or ApprovalResult member renamed, added or removed; the five synonyms stay in the enum as documented deprecated aliases and the cleanup (with tests/test_domain_enums.py) is a Phase 12 follow-up in D044 (D-15)"
  - "ROADMAP Phase 11 Requirements line describes the 13 new IDs by count and phase range without listing them, so roadmap tooling does not attribute them to Phase 11"
  - "F-128 gets no new ID: it is covered by the existing OPS-02 (Phases 18 and 24), recorded in D045"
  - "The rule 'one open position per symbol' (audit F-303) was not added to RISK-04 because it is unratified"

coverage:
  - id: D1
    description: "GLOSSARY section 9 has one canonical code per concept, aliases listed, union equals the 23-member enum, and every code src/ references is canonical; section 10 lists ApprovalResult"
    requirement: "none (D-15)"
    verification:
      - kind: unit
        ref: "tests/test_decision_alignment_bookkeeping.py (GL-01..GL-06 positive, pre-change and synthetic negative tests)"
        status: pass
    human_judgment: false
  - id: D2
    description: "13 lost MUST-level requirements registered with phase traceability and ROADMAP lines; all Pending"
    requirement: "none (D-16)"
    verification:
      - kind: unit
        ref: "tests/test_decision_alignment_bookkeeping.py (RQ-01..RQ-05 and no-new-ID-complete test)"
        status: pass
    human_judgment: false
  - id: D3
    description: "D044 and D045 appended contiguously with owned follow-ups and explicit exclusions; DOC_STATUS log and DATA_MODEL notes present"
    requirement: "none (D-16, D-19)"
    verification:
      - kind: unit
        ref: "tests/test_decision_alignment_bookkeeping.py (DC-01..DC-06, owner phases exist in ROADMAP)"
        status: pass
    human_judgment: false
  - id: D4
    description: "Whether the collapsed canonical/alias split and the ApprovalResult value set are the intended vocabulary"
    requirement: "none"
    human_judgment: true
    rationale: "ApprovalResult was a Phase 3 planner assumption still awaiting user ratification (STATE blocker); the alias replacements are a documentation choice for Phase 12 to confirm"
---

# Phase 11 Plan 07: Authority Chain Bookkeeping Summary

**GLOSSARY now lists one canonical rejection code per concept (derived from what src/ actually references) with five deprecated aliases, the plain-string codes and SAFE_MODE reasons the code emits, and ApprovalResult; 13 lost MUST-level rules are registered as requirement IDs mapped to phases 13-26; D044 and D045 record the alignment, its ten owned follow-ups and the deliberate exclusions; a 17-gate module checks all of it.**

## Performance

- **Completed:** 2026-09-30
- **Tasks:** 3 (1 tracer, 2 auto/tdd) plus one typing cleanup commit
- **Files:** 2 created, 6 modified; nothing under `src/` or `tests/test_domain_enums.py` touched by this plan

## Accomplishments

- **Derivation matched F8.** `grep -rhoE "RejectionReason\.[A-Z_]+" src --include=*.py` excluding `enums.py` returns exactly the 17 expected codes; `referenced_reason_codes()` reproduces it in Python and a test pins the set. GLOSSARY 9.1 lists those 17 plus `INSUFFICIENT_MARGIN` (reserved, first emitted by the Phase 22 margin guard): 18 tokens. 9.2 lists the five aliases with canonical replacement and cleanup owner Phase 12. 18 + 5 = 23 = `RejectionReason` members.
- **9.3 and 9.4 derived from src/, not memory.** Plain-string codes with emitting files: `DISABLED`, `ENTRY_WITHOUT_PROTECTIVE`, `NO_FILL`, `HEALTH_CHECK_FAILED`, `EXPIRED` (labelled an outcome label, not a rejection reason), and `OK`, `WARMUP_INSUFFICIENT`, `GAP_IN_SOURCE`, `INVALID_INPUT` from `src/core/types.py` (labelled not rejection reasons). SAFE_MODE entry reasons found: `ENTRY_WITHOUT_PROTECTIVE`, `ORPHAN_PROTECTIVE`, `API_DEGRADATION`, `STALE_FEED`, `DB_FAILURE`, `MANUAL_CLOSE`, `REGISTRY_DIFF`, plus `ENTRY_STATE_UNKNOWN`, which the code emits in `src/execution/manager.py` but F8 did not list. Section 8.2 (KillGateState block) is untouched (GL-06 and `tests/test_kill_gate_docs.py` pass).
- **Section 10.** `text` block PENDING, APPROVED, SKIPPED, EXPIRED; mapping from `action_to_result` (APPROVE to APPROVED; SKIP_USER, SKIP_BUSY, CANCEL to SKIPPED; SIMULATE to PENDING); noted as a Phase 3 planner assumption pending user ratification.
- **REQUIREMENTS.** RISK-03, RISK-04, EXEC-04..EXEC-07, DOMN-04, BKTS-04, OPS-03..OPS-06, GOV-02 added in their area sections, traceability rows appended (phases 20, 19, 17, 18, 20, 19, 17, 14, 24, 24, 20, 13, 26), coverage 43/43/0, footer dated 2026-09-30. All Pending.
- **ROADMAP.** Ten scoped single-line edits: Requirements lines of phases 11, 13, 14, 17, 18, 19, 20, 24, 26, the two "is to be added" sentences removed, and one sentence appended to Phase 13 criterion 2 (freeze and hash `research-universe-v1.toml`, DRAFT to FROZEN, check history depth against the D043 trade floor, report a shortfall instead of lowering the floor).
- **DECISIONS.** D044 (Accepted 2026-09-30, no new decision content) lists the Phase 11 artifacts and follow-ups (1)-(10) with owner phases 12, 13, 14, 17, 18, 20, 22, 24, 26; D045 records the three not-built entities, the application-level secret encryption exclusion, and the lost-requirement dispositions (F-105, F-111, F-118, F-103, F-104, F-106 mapped to IDs; F-128 covered by OPS-02). Only two lines appended (`git show 7cdfccf -- docs/DECISIONS.md`: 2 added, 0 removed rows).
- **DOC_STATUS, DATA_MODEL.** One change-log line naming the documents amended by Phase 11 and D044/D045; sections 2.2, 2.6, 2.12 each gain "V1 status: not built (D045)." with one clause; field lists unchanged.

## Task Commits

1. Task 1 (tracer): `614cdcc` - GLOSSARY sections 9 and 10, gates GL-01..GL-06
2. Task 2: `daa0698` - REQUIREMENTS 13 IDs, ROADMAP requirement lines, gates RQ-01..RQ-05
3. Task 3: `7cdfccf` - DECISIONS D044/D045, DOC_STATUS, DATA_MODEL notes, gates DC-01..DC-06
4. Cleanup: `63b8670` - type parsed sections as `dict[str, Any]` (mypy clean without ignores)

## Verification

- `pytest tests/test_decision_alignment_bookkeeping.py tests/test_kill_gate_docs.py tests/test_domain_enums.py tests/test_research_gate_negative.py -q -p no:cacheprovider`: all passed (bookkeeping file: 32 passed); no skips reported with `-rs`. Wider run with all `tests/test_decision_alignment_*.py`: all passed.
- `bookkeeping.run()`: 17 gates, 0 failed.
- `ruff check` clean, `ruff format` applied, `mypy` on the module clean.
- RED observed before each GREEN (Task 1: 2 real-repo failures; Task 2: 5 failures; Task 3: 4 failures).
- `git diff 679825c --stat -- .planning/ROADMAP.md`: 27 insertions, 13 deletions, which is this plan's ten line edits plus the earlier planner and progress-table changes from other plans.

## Deviations from Plan

**1. [Ordering] Tracer and TDD RED/GREEN committed together per task.** Same convention as plans 11-01..11-06: RED was run and observed but each task is one commit with tests and implementation.

**2. [Scope note] Acceptance "git diff 679825c --stat -- src/ tests/test_domain_enums.py is empty"** does not hold because plan 11-02 changed `src/domain/registry.py`. This plan changed nothing under `src/` and did not touch `tests/test_domain_enums.py`.

**3. [Additional] `ENTRY_STATE_UNKNOWN`** is listed in GLOSSARY 9.4 although the plan's list of SAFE_MODE reasons did not name it; it is emitted in `src/execution/manager.py` and the plan said to follow the code.

**4. [Cleanup commit]** A fourth commit removed `# type: ignore` comments by typing the parser result as `dict[str, Any]` after mypy flagged them.

**Total deviations:** 0 fixes, 4 notes. **Impact:** none on content.

## Issues Encountered

- CRLF working tree warnings from git (docs are CRLF, planning files LF); commits are unaffected.
- An early heredoc used to build the gate code had its escape sequences collapsed once, producing literal newlines inside regex strings; caught by reading the file back and repaired before any test or commit.

## Known Stubs

None.

## Threat Flags

None. T-11-17 (silent drops) is mitigated by RQ-01..RQ-05 and D045; T-11-18 (reason-code drift) by GL-02/GL-03 and the D044 follow-up owners; T-11-19 (DECISIONS table corruption) by DC-01/DC-02 and the two-line append.

## Next Phase Readiness

Ready for 11-08 (still owes RISK-02, EXEC-02, OPS-01 completion). Follow-ups are recorded in D044 with owner phases; the ApprovalResult ratification stays a STATE blocker.

## Self-Check: PASSED

Created files exist (`bookkeeping.py`, its test file); commits 614cdcc, daa0698, 7cdfccf, 63b8670 found in git log; all task acceptance commands and the plan `<verification>` commands re-run green.
