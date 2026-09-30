---
phase: 12-fee-cost-model-correctness
plan: 01
subsystem: risk-vocabulary
tags: [rejection-reason, glossary, decision-alignment-gates, enum-cleanup]
status: complete

requires:
  - phase: 11
    provides: GLOSSARY section 9 canonical-code block, GL-01..GL-06 gates, D044 alias-cleanup follow-up
provides:
  - RejectionReason with 20 members (STOP_TOO_TIGHT and COST_TO_RISK_EXCEEDED added, five aliases removed)
  - GLOSSARY 9.1 (20 codes) and 9.2 (retired-alias record)
  - RETIRED_ALIASES and reworked GL-01/GL-03 that fail if a retired name re-enters
affects: [12-06 cost guards, 12-09 backtest simulator test set, 12-11 decision rows]

actuals:
  tokens: 4800
  tasks: 2
  commits: 4

commits: 4
plan_head_before: bce5a978c0f8a17f50420ecaa7f67aa8039220ab
plan_head_after: e6001bd5a3e696691b0960a08f207053f4d07a0a

tech-stack:
  added: []
  patterns:
    - "GLOSSARY first, then enum, then gates/tests in one edit window (D016)"
    - "Retired-name record table + gate that keeps the names out (negative gate)"

key-files:
  created: []
  modified:
    - docs/GLOSSARY.md
    - src/domain/enums.py
    - tests/test_domain_enums.py
    - scripts/decision_alignment/bookkeeping.py
    - tests/test_decision_alignment_bookkeeping.py

key-decisions:
  - "9.2 table keeps its first-column shape so parse_glossary_sections still returns it under the existing 'aliases' key; GL-03 compares it to RETIRED_ALIASES instead of adding it to the enum union."
  - "referenced_reason_codes test is a superset/subset pair (17 required, only the two Phase 12 codes permitted extra) so plan 12-06 needs no test edit."

requirements-completed: [RISK-01]

coverage:
  - deliverable: "RejectionReason has exactly 20 members incl. STOP_TOO_TIGHT and COST_TO_RISK_EXCEEDED, no retired alias"
    verification:
      - kind: test
        ref: "tests/test_domain_enums.py#test_rejection_reason_values_match_glossary_section_9"
        status: pass
    human_judgment: false
  - deliverable: "SizedResult and PortfolioVerdict accept the new codes and reject invented ones"
    verification:
      - kind: test
        ref: "tests/test_domain_enums.py#test_sized_result_accepts_new_cost_guard_codes"
        status: pass
      - kind: test
        ref: "tests/test_domain_enums.py#test_portfolio_verdict_accepts_new_cost_guard_codes"
        status: pass
    human_judgment: false
  - deliverable: "GL gates fail when a retired alias re-enters the enum, the 9.1 block, or the 9.2 table loses a row"
    verification:
      - kind: test
        ref: "tests/test_decision_alignment_bookkeeping.py#test_retired_alias_added_to_enum_values_fails_gl03"
        status: pass
      - kind: command
        ref: ".venv/Scripts/python scripts/verify_decision_alignment.py glossary"
        status: pass
    human_judgment: false
---

# Phase 12 Plan 01: Rejection-vocabulary edit window Summary

**RejectionReason goes from 23 to 20 members: STOP_TOO_TIGHT and COST_TO_RISK_EXCEEDED added GLOSSARY-first, the five deprecated aliases removed and recorded in a retired-alias table, with GL-01/GL-03 reworked so a retired name can never re-enter.**

## Performance

- Tasks: 2 (1 tracer, 1 auto), both TDD with separate RED commits
- Files: 5 modified, none created
- Commits: 4 (measured from the ledger)

## Accomplishments

- GLOSSARY section 9 lead-in rewritten without deprecation wording; 9.1 block gained the two codes plus a prose line defining each (both emitted before quantization, D-07); 9.2 retitled "Retired aliases (removed in Phase 12)" with a Removed name / Use instead / Removed in table.
- `RejectionReason` now has 20 members; `INSUFFICIENT_MARGIN` and `DailyState` untouched (`DailyState.DAILY_STOP` still valid).
- `SizedResult` and `PortfolioVerdict` accept the new codes through the enum-derived `_REASON_CODES`, and still reject invented codes such as `STOP_TOO_CLOSE`.
- `bookkeeping.py`: `RETIRED_ALIASES` replaces `ALIASES`; GL-01 rejects retired names in the 9.1 block; GL-03 requires 9.1 == enum, no retired name among enum values, and 9.2 table == `RETIRED_ALIASES`. Gate ids and count (six) unchanged.
- New tests: parametrised retired-name absence, DailyState survival, GLOSSARY 9.1-equals-enum parse, negative gate cases (retired name in enum set, in 9.1 block, table row removed), superset/subset referenced-code test. Pre-change GLOSSARY still fails GL-01, GL-03, GL-04.

## Task Commits

1. Task 1 RED: `0433e2c` test(12-01) - 20-code vocabulary tests
2. Task 1 GREEN: `96fe4e3` feat(12-01) - GLOSSARY + enum
3. Task 2 RED: `67cdad8` test(12-01) - GL gate tests
4. Task 2 GREEN: `e6001bd` feat(12-01) - bookkeeping gates

## Verification

- `pytest tests/test_domain_enums.py tests/test_risk_sizing.py tests/test_risk_quantization.py`: pass
- `pytest tests/test_decision_alignment_bookkeeping.py tests/test_decision_alignment_ops_risk.py tests/test_domain_enums.py`: pass (ops_risk QUANTIZATION_REJECT docs-forbid gate unaffected)
- `scripts/verify_decision_alignment.py glossary`: `ALL_PASS glossary`
- Enum one-liner: `enum ok 20`
- `ruff check` on the four touched Python sources plus the enum: clean; `mypy src/domain/enums.py`: clean
- Full `pytest tests`: green
- `git diff --name-only bce5a97..HEAD` lists exactly the five files in `files_modified`.

## Deviations from Plan

None - plan executed exactly as written. The retired-name grep found only the expected sites (test_domain_enums, bookkeeping, a tolerant string set in tests/test_backtest_simulator.py owned by plan 12-09, and the ops_risk docs-forbid gate); the last two were left alone as instructed.

## Known Stubs

None.

## Threat Flags

None. No new network, auth, or file-access surface.

## Notes

- Working tree is CRLF (`core.autocrlf=true`); edits preserved CRLF.
- Pre-existing dirty files (`.planning/config.json`, `milestone.lock`, `state.json`, `.gsd/`) were not staged.

## Next

Ready for the next Phase 12 plan. Plan 12-06 can emit the new codes without further enum or gate edits.

## Self-Check: PASSED

All five modified files exist; commits 0433e2c, 96fe4e3, 67cdad8, e6001bd found in `git log`.
