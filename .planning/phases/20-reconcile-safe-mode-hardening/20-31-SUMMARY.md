---
phase: 20-reconcile-safe-mode-hardening
plan: 31
subsystem: reconcile
tags: [reconcile, compare, entry-without-protective, d079, fill-driven-protection, gap-closure, tdd]
requires: [20-04, 20-12, 20-28]
provides:
  - "compare Pass 2: a local ENTRY that is certainly still waiting for its first fill (local status NEW, no exposure on the symbol, exchange status NEW) is not ENTRY_WITHOUT_PROTECTIVE (W1)"
  - "tests/test_protection_deadline_attempt.py: the step that reaches max_unprotected_ms still makes its same-id re-place attempt before CLOSE_REQUIRED (W2, SC2 case 1)"
affects: [Phase 24 composition, 20-DEFERRED.md row 35 (orchestrator)]
gap_closure: true
requirements-addressed: []
status: complete
commits: 5
plan_head_before: 578b485b730073060f7f23b5658bf9d5efbf00ba
plan_head_after: 234521237171f274df6585d1d5cebca726bced82
actuals:
  tokens: 5554   # chars/4 over `git diff 578b485b HEAD -- src tests` (22216 chars)
  tasks: 2
  commits: 5     # MEASURED: git rev-list --count 578b485b..HEAD (plan + 4 task commits; this summary is committed after)
key-files:
  created:
    - tests/test_protection_deadline_attempt.py
    - .planning/phases/20-reconcile-safe-mode-hardening/20-31-PLAN.md
  modified:
    - src/reconcile/compare.py
    - tests/test_reconcile_classify.py
    - tests/test_safe_mode_exit_operator.py
    - tests/test_reconcile.py
    - tests/test_reconcile_stale_entry.py
key-decisions:
  - "The existing local-intent signal is used and no field was added: derive_local_intent already gives the entry of a plan in AWAITING_FILL the status NEW and every other entry state SUBMITTING or PARTIALLY_FILLED."
  - "An entry missing from the exchange keeps BOTH ENTRY_WITHOUT_PROTECTIVE and UNSYNCED_NORMAL. An absent order is not proof of 'no fill' (filled, expired or cancelled all look the same), and tests/test_phase8_audit_reviewfix.py::test_wr13_missing_entry_without_protection_yields_both pins exactly that. The first version of the change dropped the first kind for an absent entry; that test caught it and the rule was narrowed (commit a1def018)."
  - "Exposure on the symbol means a non-zero exchange position OR a non-zero local position intent; a One-way position is the symbol's total, so another plan's position never excuses an unfilled entry."
---

# Phase 20 Plan 31: resting-entry rule and deadline-attempt test Summary

**A resting GTD entry that has had no fill no longer yields ENTRY_WITHOUT_PROTECTIVE, so a pending approved entry no longer causes a CRITICAL UNPROTECTED_POSITION alert, SAFE_MODE, or a refused operator SAFE_MODE exit; every sign of a fill still does. The deadline step of the SC2 case (1) rule is now pinned by a test and the code already behaved as documented.**

Evidence label: executed unit tests with fakes and the local PostgreSQL gate tests. Nothing was run against Binance or Telegram; nothing is `[DEMO]`. No requirement is marked complete (`requirements-addressed: []`). Live placement stays disabled. `src/execution/protection.py` was not changed (only a temporary mutation for a sensitivity check, restored with `git checkout -- src/execution/protection.py`).

Base `578b485b` (develop), branch `p20-31`. `commits: 5` is the measured `git rev-list --count 578b485b..HEAD` at SUMMARY write.

## W1 - what changed

`src/reconcile/compare.py`, Pass 2: the divergence is emitted unless `_entry_awaits_fill(...)` is true. That helper is true only when ALL hold:

1. the local status of the entry is exactly `NEW` (AWAITING_FILL); PLANNED, SUBMITTING (ENTRY_UNRESOLVED and every SENT/UNKNOWN row), PARTIALLY_FILLED, a missing status and any other value mean "may have filled";
2. the symbol carries no exposure: no non-zero exchange position row (a zero amount is not a fill) and no non-zero local position intent;
3. the exchange lists the entry among its open orders with status exactly `NEW` (PARTIALLY_FILLED, FILLED, an unknown or empty status keep the divergence).

An entry missing from the exchange keeps both ENTRY_WITHOUT_PROTECTIVE and UNSYNCED_NORMAL, as before. Nothing else in compare changed (the sweeper exemption `resting_entry_plans`, Pass 1, 1b and 3 are untouched). The classify table, the alert vocabulary and `loop.py` needed no change: with no divergence there is no UNPROTECTED_POSITION alert and no SAFE_MODE reason, shown by a tick test; with a position on the symbol the alert and the reason are still raised, shown by a second tick test.

## Tests

- `tests/test_reconcile_classify.py`: the pinned `test_observed_limit_a_resting_entry_with_no_fill_is_entry_without_protective` was replaced by 13 test functions (some parametrized): unfilled resting entry agrees; a zero-amount row is not a fill; a position on the symbol, exchange statuses PARTIALLY_FILLED / FILLED / UNKNOWN / empty, a missing entry (both kinds), an unresolved entry (SUBMITTING and a SENT row), local statuses PARTIALLY_FILLED / SUBMITTING / PLANNED / None, and a local position intent on the symbol all keep the divergence; a position on another symbol and a protected plan on another symbol do not; two tick tests (no SAFE_MODE and no alert for the unfilled entry; alert and SAFE_MODE with a position).
- `tests/test_safe_mode_exit_operator.py`: three exit tests (an unfilled resting GTD entry does not refuse the exit; with a position on the symbol, or with the entry gone, the exit is refused as COMPARE_NOT_CLEAN).
- `tests/test_reconcile.py::test_entry_without_protective_divergence_does_not_sweep` pinned the old rule with a NEW resting entry; its purpose (a non-orphan divergence never makes the sweeper cancel) is kept by making the entry a PARTIALLY_FILLED one (local and exchange row). Assertions are unchanged.
- `tests/test_reconcile_stale_entry.py`: `set(enter_calls) <= {"ENTRY_WITHOUT_PROTECTIVE"}` became `enter_calls == []` (the 20-28 SUMMARY finding 5 said this allowance existed only because of W1).

## W2 - what was found

`tests/test_protection_deadline_attempt.py` (3 tests, reusing the rig of `tests/test_protection_demo_shapes.py`): with the by-id query and the listing both denying a stop that rests, the placement count rises by one across the step that reaches `max_unprotected_ms`, the state ends CLOSE_REQUIRED with `B2_STOP_UNCONFIRMED`, every attempt carries the same client id and the plan trigger price, and the attempt precedes any `place_market_close`; when the listing shows the stop the deadline step makes no attempt and does not escalate. The code already behaves as the criterion says (`_supervise_plan` places in the ABSENT branch before the deadline check), so nothing was reported as a code defect.

## TDD Gate Compliance

`gsd_run check tdd-red-evidence` was not run (it does not parse pytest output). Honest RED evidence:

- W1 RED, commit `b557b83d`: run of `tests/test_reconcile_classify.py tests/test_safe_mode_exit_operator.py` showed 7 failed, the rest passed. The 7: `test_a_resting_entry_with_no_fill_is_agreement`, `test_a_zero_amount_exchange_row_is_not_a_fill`, `test_a_tick_over_a_resting_unfilled_entry_enters_no_safe_mode_and_alerts_nothing`, `test_a_position_on_another_symbol_does_not_make_the_entry_filled`, `test_an_awaiting_entry_missing_on_the_exchange_stays_unsynced_normal` (the first version of that test, later reversed), `test_a_resting_entry_next_to_a_protected_plan_on_another_symbol_agrees`, `test_row4_an_unfilled_resting_gtd_entry_does_not_refuse_the_exit`. The fail-closed tests (position, statuses, local statuses, unresolved) pass before and after: they pin behavior that must not regress, they are not new RED.
- The first GREEN (`c87e79cf`) broke `tests/test_phase8_audit_reviewfix.py::test_wr13_missing_entry_without_protection_yields_both` and `tests/test_reconcile.py::test_entry_without_protective_divergence_does_not_sweep`. The first was fixed in the code (rule narrowed, `a1def018`, and my own test reversed to pin both kinds); the second pinned the old rule with a resting NEW entry and was updated as described above.
- W2 has no RED: the three tests passed on first run because the code is right. Sensitivity check: a temporary change of the ABSENT branch to `elif reading is ABSENT and not self._unprotected_deadline_reached(tracked)` made 2 of the 3 new tests fail (`assert 1 == (1 + 1)`), while the existing `test_protection_demo_shapes.py` stayed green (the gap W2 described). `protection.py` was restored; `git status` showed no change to it.

## Deviations from Plan

**1. [Rule 1 - own defect, caught by an existing pin] The first W1 version dropped ENTRY_WITHOUT_PROTECTIVE for an entry missing from the exchange.** `test_wr13_missing_entry_without_protection_yields_both` caught it. The task text allowed either reading ("stays the existing UNSYNCED_NORMAL divergence"); the narrower exemption keeps the existing behavior and the existing pin, and is fail closed. A natural GTD expiry that the coordinator has not yet seen therefore still shows both kinds until the coordinator learns the entry ended (see findings).

**2. [Rule 3] `uv sync --frozen --extra dev` was needed in the new worktree** (its `.venv` was empty); no dependency file changed.

**3. [Process] Line endings.** The working tree of src and tests is CRLF (index LF). A first edit through Python text mode mixed endings in two test files; both were normalized to all-CRLF before the first commit and `git diff` shows only the intended lines. `.codegraph/` does not exist in the worktree, so `codegraph explore` was not used.

No threat-model or Rule 4 item arose.

## Findings for the orchestrator / later plans

1. **Docs to update (orchestrator, not edited here):** `20-DEFERRED.md` row 35 and the Phase 24 blocker row 136 (`ENTRY_WITHOUT_PROTECTIVE` for resting entries) are now closed for the "no fill, entry resting" case; the second half of row 136 (`-1013`) is unrelated. The 20-12 SUMMARY finding 1 and the 20-28 SUMMARY finding 5 are resolved. The module docstring of `compare.py` was updated. `docs/GLOSSARY.md` 9.1/9.4 describe `ENTRY_WITHOUT_PROTECTIVE` as the rejection reason "an entry fill exists without a confirmed protective stop"; that wording was already right and needed no edit, but it has no row for the reconcile divergence kind, so the new exemption is documented only in `compare.py`. The RUNBOOK SAFE_MODE exit text (21.1) may mention that a resting GTD entry no longer blocks the exit; I did not open it (the orchestrator owns it).
2. **A stale feed plus a pending GTD entry** (the combination the DEFERRED row warned about) now gives only `STALE_FEED`.
3. **Residual false alarm:** an entry that expired or was cancelled on the exchange before the coordinator marked the plan ENTRY_ENDED_NO_FILL still gives ENTRY_WITHOUT_PROTECTIVE + UNSYNCED_NORMAL (fail closed, one tick or so). If the owner prefers only UNSYNCED_NORMAL for a vanished unfilled entry with no exposure, it is a one-line change in `_entry_awaits_fill` plus the reversal of `test_wr13...` and of the missing-entry test here; it was not done because it narrows a pinned fail-closed rule.
4. **Partial fill by the exchange row:** `OpenOrderSnapshot` has no executed-quantity field; a partial fill is recognized only by the exchange status PARTIALLY_FILLED, a position on the symbol, or the local status. A fill the exchange row does not yet show and no position shows would be missed for one tick; the user-data fill stream and the coordinator cover it.

## Verification actually run

All with `TRADING_CI_STRICT=1` and `TEST_DATABASE_URL` from the process environment (never echoed), final code state (`a1def018`):

- 32 test files in one run: `test_reconcile`, `_compare_v2`, `_loop`, `_stale_entry`, `_queue_order`, `_stream_divergences`, `_tp1_fill`, `_classify`, `test_safe_mode_reentry`, `_persistence`, `_persistence_pg`, `_exit_operator`, `test_alert_producers`, `test_alerts`, `test_alerts_ops05_matrix`, `test_execution_health`, `test_protection_supervision`, `_take_profits`, `_demo_shapes`, `_deadline_attempt`, `test_symbol_ownership`, `test_feed_freshness`, `_skew`, `test_controller_rehydrate`, `test_manual_controls`, `test_startup_recovery`, `test_drills`, `test_demo_rehearsal_flow`, `test_phase8_audit_reviewfix`, `test_phase18_gate`, `test_phase19_gate`, `test_phase20_gate`, `test_persistence_exit_evidence_pg`: 1237 passed, 0 skipped, 0 failed (counted from the progress dots; the quiet output prints no summary line).
- `uv run pytest -m "not docker" tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_phase20_gate.py tests/test_persistence_exit_evidence_pg.py -rs`: all passed, nothing skipped.
- `uv run mypy src`: no issues in 235 source files. `uv run ruff check`: all checks passed. `uv run ruff format --check`: 737 files already formatted. `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS.
- The full suite was not run (orchestrator).

## Known Stubs

None.

## Threat Flags

None. The change only narrows when a divergence is reported, and only on positive local and exchange evidence of "no fill"; fail-closed cases are tested one by one.

## Self-Check: PASSED

Files exist (`src/reconcile/compare.py`, `tests/test_protection_deadline_attempt.py`, this plan and summary); commits `b557b83d`, `c87e79cf`, `a1def018`, `53133143`, `23452123` exist on `p20-31`.
