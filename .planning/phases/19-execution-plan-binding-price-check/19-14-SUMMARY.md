---
phase: 19-execution-plan-binding-price-check
plan: 14
subsystem: execution
tags: [protection, failure-branches, deadlines, close-required, emergency-close, tdd, binance]
requires: ["19-11", "19-12"]
provides:
  - "src/execution/protection.py: branch codes B1_ENTRY_NOT_TERMINAL, B2_STOP_UNCONFIRMED, B3_BOTH_AMBIGUOUS, B4_FILL_AFTER_STOP, B5_STOP_REJECTED, NO_POSITION_ON_STOP_BUT_EXPOSED; SAFE_MODE reason CLOSE_REQUIRED; alert event CLOSE_REQUIRED; journal events STOP_NOT_SENT, PROTECTION_ENTRY_CANCEL_NOT_SENT, PROTECTION_CLOSE_REQUIRED, PROTECTION_CLOSE_ATTEMPT_ERROR, PROTECTION_SWEEP_FAILED; transitions into CLOSE_REQUIRED, CLOSE_FAILED, FLAT; orphan sweep after FLAT"
  - "tests/test_protection_branches.py: one deterministic race test per D-12 branch plus -4509, Q4 refusals, CLOSE_FAILED retries and transition determinism"
  - "tests/support/protection_doubles.py: make_rig(real_closer=True, closer_results=...), lot_filters_for_tests"
affects: [19-15, 19-16, 19-17]
actuals:
  tokens: 16100
  tasks: 3
  commits: 6
status: complete
commits: 6
plan_head_before: f7889b98a798c69471f7bbd2c57bf0f02595af15
plan_head_after: dc532bd964ea423d64d111ed24a4b9c5845b5063
tech-stack:
  added: []
  patterns: [integer-millisecond deadlines by timedelta floor division, REST-is-truth supervision step, query-before-replace of a stop under its deterministic id, lazy import to break the manager/live_context/protection cycle]
key-files:
  created: [tests/test_protection_branches.py]
  modified: [src/execution/protection.py, tests/support/protection_doubles.py]
key-decisions:
  - "A stop REST proved absent (query found=False) is re-placed under the same deterministic id; a stop that answers any non-ACTIVE status is never re-placed (waits for the deadline), and a failed query never triggers a re-place after the first placement"
  - "B4 and the stop-consumed case are decided by the REST position, never by the algo status class; once a stop was confirmed it is queried every step while the entry is open"
  - "B2 versus B3 at max_unprotected_ms is chosen by whether the entry is known terminal"
  - "A PreSendRefusal of the stop or of the entry cancel is journaled as not sent (STOP_NOT_SENT / PROTECTION_ENTRY_CANCEL_NOT_SENT with the refusal reason); the STOP_LOSS intent stays SENT and no SAFE_MODE comes from the refusal itself"
  - "A close that does not end flat (any non-True answer, including NOT_SENT) is CLOSE_FAILED; CLOSE_FAILED goes straight to FLAT when REST is flat and the entry terminal"
requirements-completed: [EXEC-01, EXEC-02, RISK-04]
---

# Phase 19 Plan 14: Protection failure branches, deadlines and automatic close Summary

The protection coordinator now completes the D-12 failure branches of 19-NOTES.md "Fill, stop and entry remainder" (B1 to B5, -4509), the two separate D-13 deadlines on virtual time, the taxonomy reading of the stop failure (D-21) and the D034 automatic close through the 19-12 emergency closer, ending in FLAT with an orphan sweep or in SAFE_MODE with an alert, never in silence.

## What was built

1. **Tracer, B5 (Task 1).** The stop placement failure is read with `adapter.error_facts` + `classify(..., PLACEMENT)`, never the message text (a source test pins this). `REJECTED_DEFINITIVE` (-2021) marks the STOP_LOSS intent REJECTED and enters CLOSE_REQUIRED once per plan: SAFE_MODE(`CLOSE_REQUIRED`), critical alert `CLOSE_REQUIRED` with the branch code as reason, the journaled transition reason, then `emergency_closer.close_position`. The stop is never resent. Each later step (CLOSE_REQUIRED or CLOSE_FAILED) reads the entry (cancelling its remainder again while it is open), calls the closer again, and moves to FLAT only when the entry was terminal before the close and REST shows flat; then `cancel_untriggered_protectives` sweeps SL/TP1/TP2 by deterministic id once (retried per step only if it fails).
2. **B1, B2, B3 and the deadlines (Task 2).** `_confirm` queries the stop (until confirmed, and while the entry is open afterwards) and the entry by id every step, re-issues the entry cancel while the entry is not terminal, and applies two independent integer-millisecond checks from `first_fill_at` (reached means escalate): `entry_terminal_timeout_ms` only when the stop is confirmed (B1, the stop is kept, no TP, accepted-knowingly reason journaled as `PROTECTION_CLOSE_REQUIRED`), `max_unprotected_ms` only while the stop is unconfirmed (B2 if the entry is terminal, else B3). A stop REST proved absent is re-placed under the same id.
3. **B4, -4509, refusals, CLOSE_FAILED (Task 3).** A once-confirmed stop that is no longer ACTIVE (found with another status, or absent) triggers a position read: exposed is B4 (`CLOSE_REQUIRED`, the stop is never re-placed, the new exposure is closed by MARKET), flat with a terminal entry is FLAT (`STOP_CONSUMED_FLAT`). -4509 (`PRECONDITION_NO_POSITION`) reads the position: flat and entry terminal is FLAT without any close, open is `NO_POSITION_ON_STOP_BUT_EXPOSED`, flat with an open entry stays UNPROTECTED and watched. A `PreSendRefusal` is journaled as not sent and nothing else changes (the deadline keeps running; a refused close becomes CLOSE_FAILED with reason `CLOSE_NOT_SENT`). CLOSE_FAILED keeps `blocks_new_entries()` True and retries the close every step.

## Branch-to-test map (tests/test_protection_branches.py)

| Branch | Test |
|---|---|
| B5 (-2021 after a fill) | `test_branch_b5_definitive_stop_rejection_after_a_fill_closes_and_ends_flat`, `test_branch_b5_never_reads_exception_message_text` |
| B1 | `test_branch_b1_slow_entry_cancel_keeps_the_stop_then_closes_at_its_own_deadline` (asserts no `cancel_algo_order` before the close, stop kept open, FLAT after the cancel goes through, sweep after the close) |
| B2 and the boundary | `test_branch_b2_entry_terminal_stop_unconfirmed_closes_at_max_unprotected_ms` (7776 ms no, 7777 ms yes), `test_branch_b2_a_stop_active_one_step_before_the_deadline_avoids_close_required` |
| B3 | `test_branch_b3_both_ambiguous_requeries_and_recancels_then_closes_at_the_deadline` |
| Replace only after absence | `test_branch_ambiguous_stop_is_replaced_only_after_a_definitive_absence_probe` |
| Separate deadlines | `test_branch_deadlines_are_separate_...`, `test_branch_a_small_unprotected_limit_does_not_cut_the_entry_timeout_short` |
| B4 (RISK-04) | `test_branch_b4_risk04_fill_after_the_stop_triggered_closes_and_never_replaces`, `test_branch_b4_is_decided_by_position_not_by_the_algo_status_class`, `test_branch_stop_consumed_with_a_flat_position_and_terminal_entry_ends_flat` |
| -4509 | `test_branch_no_position_4509_flat_and_entry_terminal_ends_flat_without_a_close`, `..._but_the_position_is_open_goes_close_required`, `..._flat_with_an_open_entry_keeps_watching` |
| Q4 refusals | `test_branch_q4_refused_stop_is_journaled_not_sent_and_the_deadline_still_escalates`, `test_branch_q4_refused_entry_cancel_is_journaled_not_sent` |
| CLOSE_FAILED | `test_branch_close_failed_keeps_blocking_and_retries_every_step_until_flat` |
| One deterministic record per transition | `test_branch_every_transition_writes_one_deterministic_journal_record` |

`uv run pytest -m "not docker" tests/test_protection_branches.py -k "branch or risk04"` selects 19 tests (all of the above).

## Open items (recorded, not decided)

- **Q4 / Phase 18 src/WR-12**: a 418/429 pause refuses the stop, the cancel and the close. This plan adds no exemption and does NOT claim "never naked" for that window: every refused call is journaled as not sent, the deadline keeps running, escalation to CLOSE_REQUIRED/CLOSE_FAILED with SAFE_MODE and a critical alert is attempted on time. The full fix (a reduce-risk exemption or a durable pending record) is the owner's decision.
- **A3**: whether a closePosition stop is auto-cancelled when the position closes (probe 6) is not assumed; the stop is kept until the close returned and swept by id after FLAT, whatever the exchange does.
- **A2**: a GTD expiry reported as EXPIRED and terminal is relied on only through `TERMINAL_ENTRY_STATUSES` (unchanged).
- Entry `found=False` on the REST query is not treated as terminal; an entry that cannot be found keeps the plan in CLOSE_REQUIRED (fail closed).
- Step cadence versus `max_unprotected_ms` is a Phase 24 number; a coarse cadence delays escalation by up to one step.
- A rate-limit window longer than `max_unprotected_ms` still leaves the position exposed and CLOSE_FAILED until the pause ends (journaled and alerted, not prevented).
- Evidence labels: -2021 and -4509 are Demo-observed only, the -2022/-2024 answers of a reduce-only MARKET are a fake TEST CONVENTION, TEST_ONLY deadlines are not ratified values (O-04); a green test proves agreement with the fake, not with mainnet.

## Deviations from Plan

**1. [Process] B4 and the stop-consumed handler landed in the Task 2 GREEN commit.** The supervision rewrite (`_confirm`) needed the "stop no longer ACTIVE" branch to keep stop reads consistent, so `_on_stop_lost` (B4, stop-consumed-flat) was written with Task 2. The Task 3 tests for B4, the "by position not by status class" test and the stop-consumed-flat test therefore passed on their first run and have no RED. The other Task 3 tests (-4509 x3, both Q4 tests, CLOSE_FAILED, determinism) were RED first (5 failures) and are GREEN in the Task 3 commit. No behavior was added without a test; the assertions would fail if `_on_stop_lost` were removed.

**2. [Rule 3 - Blocking] Lazy import of `cancel_untriggered_protectives` inside `_sweep`.** `manager` imports `live_context`, which imports `protection`; a module-level import would be circular. The import sits inside the method; `test_protection_module_is_pure` still passes (`src.execution.manager` is within the allowed `src.execution.*`). A `# type: ignore[arg-type]` is on the adapter argument (Protocol-typed `ExecutionAdapter` versus the coordinator's `ProtectionAdapter`).

**3. [Scope] Test-support additions.** `make_rig` gained `real_closer` and `closer_results`, and `lot_filters_for_tests()` was added, all in `tests/support/protection_doubles.py` (a file of this plan). No file outside `files_modified` changed, no one-line pin was needed.

Judgement calls inside the plan are in the `key-decisions` list above (re-place after absence only, B2/B3 split by entry terminal, CLOSE_FAILED for any non-flat close).

## Verification (real runs from WT, branch p19-14)

- `uv run pytest -m "not docker" tests/test_protection_branches.py tests/test_protection_coordinator.py tests/test_emergency_market_close.py -x`: 102 passed.
- Also run, one pytest at a time: `tests/test_protection_router_rig.py tests/test_demo_rehearsal_flow.py tests/test_execution_manager.py tests/test_paper_replay_inputs.py tests/test_paper_runtime_restart.py tests/test_domain_boundary.py tests/test_no_unratified_defaults.py tests/test_execution_emergency.py`: all passed (exit 0).
- `uv run mypy src`: Success, no issues found in 212 source files.
- `uv run ruff check`: All checks passed. `uv run ruff format --check`: 658 files already formatted.
- The whole `pytest -m "not docker"` suite was not run (memory limit, per the dispatch notes).

## Known Stubs

None.

## Threat Flags

None. T-19-35 (naked position after a rejected or unconfirmed stop): B2/B3/B5 escalate to CLOSE_REQUIRED within `max_unprotected_ms` (tests above). T-19-36 (adding to a losing position, RISK-04): B4 never re-places the stop and closes the new exposure. T-19-37 (blind resend): a definitive rejection is never resent, an ambiguous stop is re-placed only after a definitive-absence query by the same id. T-19-38 (rate-limit starvation, Q4): mitigated partially and stated as partial, see Open items. T-19-SC: no package installed or changed.

## Self-Check: PASSED

- Files exist: src/execution/protection.py, tests/test_protection_branches.py, tests/support/protection_doubles.py.
- Commits on p19-14 (RED before GREEN): 25e2ac8 test, b24e895 feat, aeaeb11 test, 25d47ab feat, fabbed7 test, dc532bd feat; `git rev-list --count f7889b9..HEAD` was 6 before this SUMMARY commit (the SUMMARY commit is not counted in `commits`).
- No STATE.md, ROADMAP.md or file outside files_modified changed.
