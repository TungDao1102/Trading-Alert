---
phase: 17-operational-persistence-layer
plan: 03
subsystem: domain
tags: [state-machine, transitions, glossary, tdd, determinism]

requires:
  - phase: 17-operational-persistence-layer
    provides: "plan 01: ExecutionIntentStatus, ApprovalConsumptionStatus, LiveInputsStatus, SystemStateKey enums"
provides:
  - "src/domain/transitions.py: TransitionKind, LEGAL_TRANSITIONS, TERMINAL_STATES, IllegalTransition, assert_transition, is_legal for Signal, TradePlan, Order, Position, Approval, ExecutionIntent"
  - "GLOSSARY section 11: six parseable transition text blocks (auto-mode default, awaiting user confirmation, D051)"
  - "GLOSSARY section 12: value sets of the four Phase 17 persistence enums"
  - "tests/test_transitions.py: enum parity, exhaustive cross-product, GLOSSARY section 11 and 12 parity"
affects: [17-10, 17-11, 17-15]

actuals:
  tokens: 14000
  tasks: 2
  commits: 4
plan_head_before: ab96e8c768957e7751ffea5bf56d877a87ba73e7
plan_head_after: 5f457152bba087150b7407cf80ace28fe89caaa4

tech-stack:
  added: []
  patterns:
    - "Documentation-as-data: GLOSSARY text blocks are parsed back by tests and compared with the Python tables and enums"
    - "Terminal states derived from empty successor sets, never restated"
    - "Read-only tables via MappingProxyType; Enum members and string values both accepted"

key-files:
  created:
    - src/domain/transitions.py
    - tests/test_transitions.py
  modified:
    - docs/GLOSSARY.md

key-decisions:
  - "Transition tables authored from the research draft (C3) as the Phase 17 auto-mode default; GLOSSARY marks them 'Accepted (auto-mode default; user to confirm)' and plan 15 records them in D051"
  - "An unchanged state is not a transition: assert_transition raises for old == new, so repositories must treat equal states as idempotent no-ops first"
  - "APPROVED -> SUPERSEDED for a TradePlan stays illegal (open point for the user)"
  - "UNKNOWN exits for Order and Position are legal moves but documented as reconciliation-only"

patterns-established:
  - "Adding an enum member without a transition-table entry fails test_every_enum_member_has_a_table_entry"

requirements-completed: [DOMN-04]

coverage:
  - id: D1
    description: "Legal-transition tables for Signal, TradePlan, Order, Position, Approval and ExecutionIntent exist once in pure code; every enum member has an entry; terminal states equal the empty-successor states"
    requirement: DOMN-04
    verification:
      - kind: unit
        ref: "tests/test_transitions.py#test_every_enum_member_has_a_table_entry"
        status: pass
      - kind: unit
        ref: "tests/test_transitions.py#test_tables_match_the_plan_objective"
        status: pass
      - kind: unit
        ref: "tests/test_transitions.py#test_terminal_states_are_states_without_successors"
        status: pass
    human_judgment: false
  - id: D2
    description: "assert_transition raises a typed IllegalTransition (ValueError with kind, old, new) for EXPIRED->APPROVED (Signal), FILLED->NEW (Order), CLOSED->OPEN (Position), unchanged states and unknown states; every listed pair passes and every unlisted pair raises"
    requirement: DOMN-04
    verification:
      - kind: unit
        ref: "tests/test_transitions.py#test_exhaustive_cross_product"
        status: pass
      - kind: unit
        ref: "tests/test_transitions.py#test_illegal_signal_expired_to_approved"
        status: pass
    human_judgment: false
  - id: D3
    description: "GLOSSARY section 11 text blocks equal LEGAL_TRANSITIONS for all six kinds; section 12 blocks equal the four persistence enums; decision-alignment gates remain green"
    requirement: DOMN-04
    verification:
      - kind: unit
        ref: "tests/test_transitions.py#test_glossary_section_11_matches_the_python_tables"
        status: pass
      - kind: unit
        ref: "tests/test_transitions.py#test_glossary_section_12_block_equals_the_enum"
        status: pass
      - kind: command
        ref: "scripts/verify_decision_alignment.py all"
        status: pass
    human_judgment: false
  - id: D4
    description: "Whether the research-draft transition tables are the right business rules (auto-mode default, not user-confirmed)"
    requirement: DOMN-04
    human_judgment: true
    rationale: "Research C3: the GLOSSARY carried value sets only; the tables are an executor-authored default pending user confirmation (manual-only item for plan 15, D051)"

duration: 12min
completed: 2026-10-01
status: complete
---

# Phase 17 Plan 03: Legal state-transition tables Summary

**Pure `src/domain/transitions.py` with typed `IllegalTransition` for the Signal, TradePlan, Order, Position, Approval and ExecutionIntent machines, written once in code and once as parseable GLOSSARY section 11 text that tests read back, plus GLOSSARY section 12 value sets for the four persistence enums.**

## Performance

- **Duration:** 12 min
- **Tasks:** 2 (both TDD, RED then GREEN)
- **Files:** 3 (2 created, 1 modified)

## Accomplishments

- DOMN-04 has an executable, documented and parity-tested definition of legal transitions. Plans 10 and 11 call `assert_transition` inside the write transaction; plan 02's terminal-state triggers use the same terminal sets (plan 10 cross-checks them in PostgreSQL).
- GLOSSARY section 11 (six subsections, 11.1-11.6) is marked as the auto-mode default awaiting user confirmation, with the open `APPROVED -> SUPERSEDED` point recorded.
- GLOSSARY section 12 (12.1-12.4) records ExecutionIntentStatus, ApprovalConsumptionStatus, LiveInputsStatus and SystemStateKey with the meaning of each value.
- Sections 8.2, 9.1-9.3 and 10 are untouched; `verify_decision_alignment.py all` is ALL_PASS.

## Task Commits

1. Task 1 RED: `8fc621d` test(17-03): RED for legal-transition tables and GLOSSARY section 11 parity
2. Task 1 GREEN: `7b7d4ae` feat(17-03): pure legal-transition tables and GLOSSARY section 11
3. Task 2 RED: `ba539e7` test(17-03): RED for GLOSSARY section 12 persistence status value sets
4. Task 2 GREEN: `5f45715` feat(17-03): GLOSSARY section 12 persistence status value sets

## Verification

- `pytest tests/test_transitions.py tests/test_domain_enums.py tests/test_decision_alignment.py tests/test_decision_alignment_bookkeeping.py tests/test_decision_alignment_authority.py`: all pass (134 tests).
- `scripts/verify_decision_alignment.py all`: ALL_PASS, exit 0.
- `mypy src`: no issues in 125 source files. `ruff check`: all checks passed. `ruff format --check src tests`: 278 files already formatted.
- Acceptance greps: one `## 11. State transitions`, one `## 12. Persistence status values`, four `### 12.` headings, `class IllegalTransition(ValueError)` present, `transitions.py` imports only stdlib and `src.domain.enums`.
- RED evidence: Task 1 RED failed at collection (`ModuleNotFoundError: src.domain.transitions`); Task 2 RED failed 5 section-12 tests with section 12 absent.

## Deviations from Plan

None - plan executed exactly as written.

Notes: bare `ruff format --check` (no paths) reports `17-RESEARCH.md` as unformattable because ruff formats code blocks in Markdown; that is pre-existing and not part of the plan's scope (`src tests` is clean).

## Known Stubs

None.

## Threat Flags

None.

## Self-Check: PASSED

- FOUND: src/domain/transitions.py, tests/test_transitions.py, docs/GLOSSARY.md sections 11 and 12
- FOUND commits: 8fc621d, 7b7d4ae, ba539e7, 5f45715
