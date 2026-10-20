---
phase: quick-261020-jua
plan: 01
subsystem: execution
tags: [q5, entry-placement, no-resend, safe-mode, tdd]
status: complete
requires:
  - phase: 19 (plans 19-15, 19-16)
    provides: protection coordinator hand-off, error taxonomy on the entry path
provides:
  - "Exactly one place_entry POST per approval; no loop, recursion or knob"
  - "found=False / probe error / indeterminate probe after an ambiguous failure = UNKNOWN + SAFE_MODE ENTRY_STATE_UNKNOWN + RECONCILIATION_REQUIRED"
  - "EXECUTION_SPEC section 10 never-resend rule"
  - "19-DEC-Q5-DRAFT.md owner draft (no DECISIONS row)"
affects: [phase-19 plan 19-17, phase-20 reconciliation]
key-files:
  modified:
    - src/execution/manager.py
    - tests/test_execution_manager.py
    - tests/test_adapter_not_found_mapping.py
    - docs/trading/EXECUTION_SPEC.md
    - .planning/STATE.md
  created:
    - .planning/phases/19-execution-plan-binding-price-check/19-DEC-Q5-DRAFT.md
decisions:
  - "Q5 (owner, 2026-10-20) implemented; a DECISIONS row stays a draft for the owner"
metrics:
  tasks: 3
  completed: 2026-10-20
estimate:
  tokens: 70000
  tasks: 3
actuals:
  tokens: 10150
  tasks: 3
  commits: 4
plan_head_before: c3574d97abf5f03ff7f29041be069a32a1f6c21f
plan_head_after: 3cc5a79d177c0d5ef4cf7e3fa975b41451fcf32a
---

# Phase quick-261020-jua Plan 01: Q5 remove the entry-placement second attempt Summary

**The entry is sent once per approval; after an ambiguous failure one probe decides between hand-off and UNKNOWN + SAFE_MODE, and found=False is never read as absence.**

## What changed

- `_place_entry_no_blind_retry` in `src/execution/manager.py` is straight-line code: one `adapter.place_entry`, at most one `query_order_by_client`. PreSendRefusal returns REFUSED, REJECTED_DEFINITIVE returns REJECTED, a non-None response returns PLACED, probe `found is True` returns EXISTS, everything else (False, None, non-bool, probe exception) returns UNKNOWN.
- Deleted: the attempt-count constant and its comment, `_ENTRY_STATE_ABSENT`, `_ENTRY_STATE_UNKNOWN_ERROR`, the manager's `UNKNOWN_EXCHANGE_ERROR` SAFE_MODE reason, the `never_retry` flag and the now-unused `safe_mode_eligible` import. `execute_approved_plan` lost the UNKNOWN_ERROR branch; the UNKNOWN branch keeps its behavior. `ENTRY_REFUSED_BEFORE_SEND` and `ENTRY_STATE_UNKNOWN` stay. `src/domain/exchange_errors.py` is untouched.
- EXECUTION_SPEC section 10 now states the never-resend rule, the five entry outcomes, why not-found is not absence, and that bounded-reconciliation numbers are owner-open (O-04). Subsection 10.1 is unchanged. Section 7.2 says "never re-sent" instead of "never re-sent blindly".
- `19-DEC-Q5-DRAFT.md` is the owner draft (status DRAFT, evidence copied from SOURCES.md and exchange_errors.py, no numbers for windows or re-probe counts).
- `.planning/STATE.md`: `current_plan` 17 in the frontmatter and `Current Plan: 17` in the body.

## Commits

| Commit | Message |
| --- | --- |
| bb89a84 | test(q5): pin one place_entry per approval and UNKNOWN on not-found after an ambiguous error (RED) |
| fffdb6e | feat(q5): send the entry once; not-found after an ambiguous error is UNKNOWN + SAFE_MODE (GREEN) |
| f0d427a | docs(q5): execution spec section 10 never re-sends a placement; draft Q5 decision for the owner |
| 3cc5a79 | docs(q5): STATE current_plan 17 (phase 19 plans 01-16 done) |

## RED failing ids (8)

- `test_definitive_absence_after_an_ambiguous_error_is_unknown_not_a_resend`
- `test_q5_place_entry_is_sent_once_for_every_error_kind[server_5xx-absent]`, `[timeout-absent]`, `[none_response-absent]`, `[unknown_error-absent]`
- `test_q5_entry_placement_has_no_resend_construct`
- `test_an_unknown_exchange_error_absent_by_the_probe_is_unknown_and_never_resent`
- `test_a_failing_error_facts_is_treated_as_an_unknown_exchange_error`

## Tests deleted or renamed

| Test | Action | Reason |
| --- | --- | --- |
| `test_definitive_absence_allows_exactly_one_retry` | renamed `..._after_an_ambiguous_error_is_unknown_not_a_resend`, now asserts one POST, UNKNOWN, SAFE_MODE | the retry no longer exists |
| `test_repeated_definitive_absence_is_bounded_no_trade` | deleted | needs a second send; covered by the 18-case table |
| `test_refusal_on_the_second_attempt_is_also_no_trade_before_send` | deleted | needs a second send; the first-send refusal is in the table |
| `test_a_second_unknown_exchange_error_is_not_retried_either` | deleted | needs a second send |
| `test_q5_the_second_entry_attempt_is_kept_and_pinned_at_two` | replaced by `test_q5_entry_placement_has_no_resend_construct` (AST guard, non-vacuous) | the pinned number is gone |
| `test_an_unknown_exchange_error_absent_by_the_probe_is_never_retried` | renamed `..._is_unknown_and_never_resent`; reason now `ENTRY_STATE_UNKNOWN` | the extra SAFE_MODE reason is gone |
| `test_a_failing_error_facts_is_treated_as_an_unknown_exchange_error` | reason now `ENTRY_STATE_UNKNOWN` | same |
| `test_ambiguous_entry_response_triggers_query_before_retry` | renamed `..._is_probed_and_never_resent` (docstring/comments) | naming only |
| new | `test_q5_place_entry_is_sent_once_for_every_error_kind` (18 cases) | the table |

Docstring-only edits: `_status_unknown`, the module docstring of `tests/test_execution_manager.py` and of `tests/test_adapter_not_found_mapping.py`.

## Verification

- Targeted run (test_execution_manager, test_exchange_error_rejections, test_adapter_not_found_mapping): 189 passed. `-k q5` collects 19, all pass.
- Full gate (10 files, `-rs`): 319 passed, 0 skipped. The four PG files (write-ahead, approval replay, exactly-once, callback redelivery) ran: 53 passed, no SKIPPED line (TEST_DATABASE_URL was set).
- `ruff check`, `ruff format --check` (659 files), `mypy src` (212 files): clean.
- Acceptance grep for the deleted names in `src/execution/manager.py` prints 0. `src/domain/exchange_errors.py` and `tests/test_exchange_error_rejections.py` are unchanged since c3574d9; `docs/DECISIONS.md` and `.planning/ROADMAP.md` are unchanged; no `19-17-*` file touched.

## Deviations from Plan

1. **[Process] Pre-commit branch assertion.** The executor protocol's worktree allow-list (`agent-*` branches) does not fit the orchestrator-designated branch `p19-15`. HEAD was verified as non-detached and not a protected branch, and every commit stayed on `p19-15`. No code impact.
2. **[Process] STATE method.** `gsd-tools state update "Current Plan" 17` fixed both lines but also rewrote `state_head` (and `last_updated`). The plan allows only the current-plan lines and `last_updated` to change, so the file was restored and the two lines were edited by hand. `last_updated` was left as is.
3. **BINANCE.md needed no edit.** `grep -i retr` shows no line that re-sends a placement after a not-found answer; section 6.2 already says a placement is never retried because of a classification.

No other deviations.

## Open items for the owner

- Accept, edit or reject `19-DEC-Q5-DRAFT.md`; a DECISIONS row (D077 or later) follows only after that.
- O-04: the numbers for bounded reconciliation (windows, re-probe counts) are not set anywhere.
- Phase 20: whether the 3-day not-found rule of restart recovery (EXECUTION_SPEC 10.1, records a young not-found intent as REJECTED) may apply to an entry that went UNKNOWN after an ambiguous placement error. Q5 argues that not-found is not proof of absence there, so this needs an explicit decision.
- Plan 19-17's owner-gap register lists Q5 and was not touched.

## Known Stubs

None.

## Threat Flags

None. T-Q5-01 and T-Q5-02 are mitigated by the table test and the AST guard.

## Self-Check: PASSED

Files exist: `src/execution/manager.py`, `tests/test_execution_manager.py`, `docs/trading/EXECUTION_SPEC.md`, `19-DEC-Q5-DRAFT.md`. Commits bb89a84, fffdb6e, f0d427a and 3cc5a79 are on branch p19-15.
