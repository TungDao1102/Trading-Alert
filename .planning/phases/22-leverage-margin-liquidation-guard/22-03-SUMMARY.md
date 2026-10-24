---
phase: 22-leverage-margin-liquidation-guard
plan: 03
subsystem: error-taxonomy
tags: [exchange-errors, taxonomy, binance, margin-type, leverage, sources, g3-001]
requires:
  - phase: 18
    provides: "ERROR_CODE_TABLE, CodeEntry, classify, the Phase 18 SOURCES.md section and its tests"
provides:
  - "nine REJECTED_DEFINITIVE PLACEMENT entries (-4046, -4047, -4048, -4028, -4161, -4168, -4209, -2027, -2028) with their own read date and source"
  - "ERROR_TABLE_PHASE22_READ_DATE, ERROR_TABLE_PHASE22_SOURCE and an optional source argument of _entry"
  - "docs/SOURCES.md section 'Facts read for Phase 22' and the closed G3-001 pointer on the Phase 11 Change-Position-Mode row"
affects: [22-06, 22-05, 22-16]
tech-stack:
  added: []
  patterns: ["per-entry read date and source on a table whose other rows keep theirs"]
key-files:
  created: []
  modified:
    - src/domain/exchange_errors.py
    - tests/test_exchange_errors.py
    - docs/SOURCES.md
    - tests/test_sources_phase18_section.py
key-decisions:
  - "The nine codes are REJECTED_DEFINITIVE on CallKind.PLACEMENT only; every other kind stays UNKNOWN_EXCHANGE_ERROR (22-RESEARCH 2.9)"
  - "-4202..-4206, -4208 and -4403 stay out of the table on purpose (not expected at 5x; fail closed)"
  - "No documentation page was re-fetched during execution; every SOURCES.md row says so"
requirements-addressed: [EXEC-01, RISK-02]
status: complete
completed: 2026-10-24
commits: 1
plan_head_before: 5674ae056fbdc428a3e70ee343ed410d69ac5bdc
plan_head_after: 085fcd317d0f9d82709335d25a8d6b59de8fff1d
actuals:
  tokens: 14000
  tasks: 2
  commits: 2
---

# Phase 22 Plan 03: Margin-type and leverage refusals in the error taxonomy, Phase 22 documentation reads Summary

A refused margin-type or leverage change, and an entry-time leverage limit, now classify as a definitive placement rejection instead of UNKNOWN_EXCHANGE_ERROR (which `safe_mode_eligible` marks True); `docs/SOURCES.md` records the Phase 22 reads and closes the Change-Position-Mode wording of inherited item G3-001.

## What was built

- `src/domain/exchange_errors.py`: constants `ERROR_TABLE_PHASE22_READ_DATE = "2026-10-23"` and `ERROR_TABLE_PHASE22_SOURCE` (`docs/SOURCES.md, Facts read for Phase 22, error-code row`), both in `__all__`; a keyword-only `source` argument of `_entry` (default `ERROR_TABLE_SOURCE`); nine new rows after `-1121`, each `_REJECT_ON_PLACEMENT`, evidence `documented`, the page name as `name`, a note that quotes the page text and says "error-code page read 2026-10-23 (22-RESEARCH.md)". The note of -4046 says that requesting the type the symbol already has is an error and not a no-op, so the guard decides by the verification read. No existing entry, read date or source changed.
- `tests/test_exchange_errors.py`: `_EXPECTED_BY_CODE` gains the nine codes (comment: added on purpose, Phase 22 plan 22-03); `_PHASE22_CODES`; `_expected_read_date` and a new `_expected_source` are code-aware; the two whole-table read-date tests exclude the Phase 22 set explicitly; new class `TestPhase22Codes` (definitive on placement for BAD_REQUEST and NOT_FOUND, UNKNOWN on QUERY/CANCEL/LISTEN_KEY/TIME, not retry-eligible, not SAFE_MODE-eligible, metadata, the -4046 wording, the 418/429/5xx/network class rules still winning, the other leverage and region codes still out of the table).
- `docs/SOURCES.md`: section `## Facts read for Phase 22 (research 2026-10-23)` with six rows (OpenAPI document, error-code page of the llms-full bundle, change-log entry of 2026-10-09, the Change-Position-Mode wording, the four support-center articles, the installed SDK 17.4.0), each with its method and limits and what stays UNVERIFIED (A1, A3, A5, A6). One pointer sentence is appended to the last cell of the Phase 11 Change-Position-Mode row; the cell still starts with "Not fetched".

## Documentation reads: none made during execution

No page was fetched by this plan. Every row of the new section, the G3-001 sentence and the nine entry notes say "cited from 22-RESEARCH (OpenAPI document read 2026-10-23); not re-fetched during execution" (plan-check addendum of 2026-10-24). The dates 2026-10-23 are the research date. The G3-001 wording is therefore re-confirmed from the research's reading of the official OpenAPI document, not from a read by this executor; the Phase 11 page itself is still not fetched.

## Verification run

- `uv run pytest -m "not docker" tests/test_exchange_errors.py tests/test_exchange_error_rejections.py tests/test_sources_phase18_section.py tests/test_decision_alignment_exchange.py tests/test_decision_alignment_ops_risk.py tests/test_deploy_docs.py tests/test_phase18_gate.py`: all pass.
- `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS.
- `uv run ruff check` and `ruff format --check` on the three Python files: clean. `uv run mypy src/domain/exchange_errors.py`: no issues.
- `git diff --exit-code -- docs/DECISIONS.md params config/binance pyproject.toml uv.lock`: clean (no dependency added).
- Evidence label: documentation reads cited from 22-RESEARCH, executed unit tests [DESIGN]. No [DEMO] claim: the behaviour of these codes on the Demo host is unobserved (plans 22-05 and 22-09 record it).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] A pin outside files_modified: `tests/test_sources_phase18_section.py::test_phase11_section_unchanged`**
- **Found during:** Task 2
- **Issue:** the plan requires one appended sentence in the Phase 11 Change-Position-Mode row, but this test hashes the whole Phase 11 section (sha256 of the original bytes). It was not named among the pins to update, and failed after the append.
- **Fix:** the original hash is kept. The test now asserts that the exact appended sentence occurs once in the section, removes it, and compares the remainder with the original hash, so the "nothing else in the register moved" guarantee is preserved and the append is itself pinned. Comment: changed on purpose, Phase 22 plan 22-03.
- **Files modified:** `tests/test_sources_phase18_section.py`
- **Commit:** 085fcd31

**2. [Process] Task 1 landed in a sibling's commit**
- **Found during:** Task 1 commit
- **Issue:** the plans run in parallel on one working tree and one git index. After this executor staged `src/domain/exchange_errors.py` and `tests/test_exchange_errors.py`, the plan 22-02 executor's `git commit` (4f0a7cd5, "feat(22-02): margin section of the execution limits...") took the staged files with it; this executor's own commit then had nothing to commit. The two files are in 4f0a7cd5 byte-for-byte as written here (115 insertions each). History was not rewritten (sequential-execution rules forbid reset).
- **Effect:** Task 1 has no `feat(22-03)` commit. The rev-list count since `plan_head_before` is 7 because it includes the sibling plans' commits; the commits that belong to this plan are 4f0a7cd5 (Task 1 content, under the 22-02 message) and 085fcd31 (Task 2). `commits: 1` in the frontmatter is the number of commits made by this executor; `actuals.commits: 2` counts the two that carry this plan's changes.

### Not done (out of scope, recorded)

- `tests/test_decision_alignment_bookkeeping.py::test_referenced_codes_are_the_seventeen_plus_optional_phase_12_codes` fails with `INSUFFICIENT_MARGIN` as an extra referenced reason code. That code is introduced by a sibling plan of this wave (`src/domain/enums.py`, `src/risk/margin_check.py`, `docs/DECISIONS.md` mention it); the test's allow-list belongs to that plan. This plan changes none of those files. Re-ran once with the same result; not edited.

## Known Stubs

None.

## Threat Flags

None. No new endpoint, auth path or file access; the threat register items T-22-07, T-22-08 and T-22-SC are mitigated as planned (placement-only rows with per-code, per-kind and per-class tests; own read date and source and an explicit "not re-fetched" statement; no dependency change).

## Self-Check: PASSED

- `src/domain/exchange_errors.py`, `tests/test_exchange_errors.py`, `docs/SOURCES.md`, `tests/test_sources_phase18_section.py` exist and carry the changes (the first two in 4f0a7cd5, the last two in 085fcd31, both ancestors of HEAD).
- `grep -c ERROR_TABLE_PHASE22_READ_DATE src/domain/exchange_errors.py` = 11; `grep -n "^## Facts read for Phase 22" docs/SOURCES.md` prints one line; the string "Facts read for Phase 22" occurs twice in `docs/SOURCES.md`.
