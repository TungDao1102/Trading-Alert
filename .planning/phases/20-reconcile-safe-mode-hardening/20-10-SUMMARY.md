---
phase: 20-reconcile-safe-mode-hardening
plan: 10
subsystem: execution-recovery
tags: [intent-recovery, unknown-entry, reconcile, fail-closed, tdd]
requires:
  - phase: 20
    provides: "plan 20-01 probe count / interval / grace keys (TEST_ONLY values in tests), plan 20-03 finalize_reconciled_resolution and RESOLUTION_RECONCILED_ABSENT / RESOLUTION_NEVER_SENT, plan 20-04 D-01a evidence"
provides:
  - "UnknownEntryResolver, UnknownEntryReport, ReconcileReadAdapter, UnknownEntryAdapter, JournalSink in src/execution/intent_recovery.py"
  - "EVENT_UNKNOWN_ENTRY_PROBE and EVENT_UNKNOWN_ENTRY_KEPT journal events"
  - "EXECUTION_INTENT as an UNKNOWN-exit entity type of src/domain/stream_records.py"
  - "resolve_unresolved_intents without the young-absent REJECTED rule for ENTRY, with the INTENDED NEVER_SENT path and the F5 skip"
affects: [20-12, 20-15, 20-22, 20-24]
status: complete
requirements-addressed: [EXEC-02]
plan_head_before: 04ea6d1abda08f0ab0a89a7739c548bf56f9ad8e
plan_head_after: 11daacf3
actuals:
  tokens: 20000   # chars/4 over `git diff 04ea6d1a 11daacf3` (79356 chars)
  tasks: 3
  commits: 5      # MEASURED: git rev-list --count 04ea6d1a..HEAD before this SUMMARY commit (1 docs + 2 RED + 2 GREEN)
key-files:
  created:
    - tests/test_intent_recovery_unknown_entry.py
  modified:
    - src/execution/intent_recovery.py
    - src/domain/stream_records.py
    - tests/test_intent_recovery.py
    - tests/test_intent_recovery_pg.py
    - tests/test_stream_records.py
key-decisions:
  - "The consecutive clean-probe count restarts on every failure (indeterminate probe, failed or inconclusive read, exposure, open order, journal or store failure); it does not restart while only waiting (probes pending, GTD plus grace not passed, GTD time unknown). An UNKNOWN_ENTRY_KEPT row is journaled, best effort, for an indeterminate probe, a failed or inconclusive read, exposure and an open order."
  - "A journal row that cannot be written is not evidence: probe row, kept row and closing row failures keep the intent UNKNOWN; nothing is finalized without the evidence row."
completed: 2026-10-21
---

# Phase 20 Plan 10: UNKNOWN entry recovery (D-11) Summary

## Owner decision O-F

Recorded 2026-10-21 from the owner's answer given in the orchestrator session, after the orchestrator presented the D-01a evidence of plan 20-04 and explained D-11, D-15 and D-24. Four independent items, one line each; acceptance of one item never implies acceptance or verification of another. Plan 20-15 reads only the D-15 line; plan 20-22 reads only the D-24 line.

D-11: accept
D-15: accept
D-01a: accept
D-24: accept

The owner's own words, verbatim (Vietnamese):

> D-11 tôi accept, nhưng N lần ở đây là bao nhiêu lần, có thể recommend cho tôi 1 con số phù hợp được không

> D-15: ... (followed, after a further explanation, by:) D-15 accept

> D-24: accept

> D-01a: accept

The owner's D-11 question (how many probes N, `reconcile.entry_unknown_probe_count`) was answered by the orchestrator with a NON-BINDING suggestion of N = 3 with 5000 ms spacing. That suggestion is NOT applied: the numeric values of `reconcile.entry_unknown_probe_count` and `reconcile.entry_unknown_probe_interval_ms` stay `NOT_CONFIGURED` (owner decision O-G, after Demo evidence), and no number was written into `config/execution/execution-limits-v1.toml`. Tests use the TEST_ONLY values of plan 20-01 (3, 2345 ms, grace 9191 ms), which are not the owner's choice.

An owner accept of D-01a is a policy acceptance, not evidence. The evidence is the executed test result below.

### D-01a evidence (copied from 20-04-SUMMARY.md, section "D-01a bound check evidence")

Command: `uv run pytest -m "not docker" tests/test_reconcile_compare_v2.py -rA` (pure unit tests, `[DESIGN]`, no exchange, no [DEMO] claim). All results were executed in the plan 20-04 worktree at `36c420d9`; the full file: 117 passed.

| Test (tests/test_reconcile_compare_v2.py) | What it shows | Result |
|---|---|---|
| test_a_protected_in_bound_long_position_agrees | LONG +0.004 against intended 0.004 with ACTIVE system SL: agreement | PASSED |
| test_sign_must_match_the_plan_side_long_and_short [LONG +0.004] | LONG, positive: agrees | PASSED |
| test_sign_must_match_the_plan_side_long_and_short [LONG -0.004] | LONG, negative: SIGN_FLIPPED_POSITION | PASSED |
| test_sign_must_match_the_plan_side_long_and_short [SHORT -0.004] | SHORT, negative: agrees | PASSED |
| test_sign_must_match_the_plan_side_long_and_short [SHORT +0.004] | SHORT, positive: SIGN_FLIPPED_POSITION | PASSED |
| test_a_flipped_sign_that_also_exceeds_the_bound_is_sign_flipped_only | LONG -0.008 and SHORT +0.008: one kind, SIGN_FLIPPED_POSITION (sign before bound) | PASSED |
| test_bound_is_abs_exchange_at_most_intended_quantity [LONG 0.004 / SHORT -0.004] | equality agrees | PASSED (2 cases) |
| test_bound_is_abs_exchange_at_most_intended_quantity [LONG 0.005 / SHORT -0.005] | intended + 0.001: DOUBLED_POSITION | PASSED (2 cases) |
| test_bound_is_abs_exchange_at_most_intended_quantity [LONG 0.008 / SHORT -0.008] | 2x intended: DOUBLED_POSITION | PASSED (2 cases) |
| test_bound_check_cannot_see_an_overfill_below_the_intended_quantity | +0.003 against intended 0.004 AGREES: the documented limit (an over-fill below the bound is invisible) | PASSED |
| test_missing_local_bound_data_fails_closed [no-plan-hash, empty-plan-hash] | missing plan_hash: AMBIGUOUS_POSITION_OWNER, agreement False | PASSED (2 cases) |
| test_missing_local_bound_data_fails_closed [no-expected-side, unknown-expected-side] | missing / invalid expected_side: AMBIGUOUS_POSITION_OWNER | PASSED (2 cases) |
| test_missing_local_bound_data_fails_closed [max-none, max-zero, max-negative, max-str, max-float, max-int, max-nan] | max_abs_amount None / zero / negative / not a Decimal / NaN: AMBIGUOUS_POSITION_OWNER | PASSED (7 cases) |
| test_none_source_is_refused_not_read_as_empty [each of the six sources] | a None source raises TypeError naming the source, no CompareDiff returned | PASSED (6 cases) |
| test_two_local_plans_on_one_symbol_is_ambiguous_and_never_picks_one | two plan hashes on one symbol: only AMBIGUOUS_POSITION_OWNER, no DOUBLED / SIGN_FLIPPED | PASSED |
| test_one_plan_hash_repeated_consistently_is_one_owner | the same plan repeated with identical data agrees | PASSED |
| test_one_plan_hash_repeated_with_different_bounds_is_ambiguous | the same plan with conflicting bounds: AMBIGUOUS_POSITION_OWNER | PASSED |
| test_a_non_decimal_exchange_position_amount_raises_type_error [str, float, int, None] | exchange amount never converted: TypeError | PASSED (4 cases) |
| test_compare_v2_has_no_float_constructor_and_no_wall_clock | no `float(...)` call and no clock read in compare.py and order_ids.py | PASSED |

Not shown by any executed test, labelled `[NOT_TESTED]`:

- `[NOT_TESTED]` Behaviour against a real Binance position read or any Demo account: nothing was run against Binance (no network, no [DEMO]).
- `[NOT_TESTED]` That the loop (plans 20-12, 20-20) refuses stale or unreadable local data before calling compare. compare has no clock and cannot judge data age; this is the caller's job and is covered by those plans, not by plan 20-04.
- `[NOT_TESTED]` Equivalence of the per-symbol check with a per-plan check; it holds only while the Phase 19 one-plan-per-symbol pre-placement rule holds (premise stated in the compare docstring, not tested).

Documented limit: an over-fill still below the intended quantity is not detectable in Phase 20 (the check is a bound, `abs(exchange) <= intended_quantity`); exact fill-ledger reconciliation is Phase 24 (D-13).

## What was built

An UNKNOWN ENTRY intent (an ambiguous send, Q5) is no longer turned into REJECTED because it is absent and younger than 3 days; it closes only through `UnknownEntryResolver`, and only on repeated, fresh, journaled Binance evidence.

- `src/execution/intent_recovery.py`
  - `UnknownEntryResolver(*, store, adapter, journal, safe_mode_controller, limits, entry_good_till)` with `async step(*, now_utc) -> UnknownEntryReport`. The constructor raises `ExecutionLimitsNotConfigured` (naming the keys, never a value) while `reconcile.entry_unknown_probe_count`, `reconcile.entry_unknown_probe_interval_ms` or `protection.entry_unknown_grace_ms` is unset.
  - Per UNKNOWN ENTRY and per step: spacing check (`NOT_DUE`), one probe by client order id, a clean `found=False` increments the count and is journaled as `UNKNOWN_ENTRY_PROBE` (source `REST_RECONCILE`); at count >= N and `now >= entry_good_till + grace` it reads `snapshot_positions(symbol=)` and `snapshot_open_normal_orders(symbol=)` in the same step, requires a zero position and no open order, journals `UNKNOWN_EXIT_EVIDENCE` (entity `EXECUTION_INTENT`, `UNKNOWN->REJECTED`, `REST_RECONCILE`, reference = client order id), then calls `finalize_reconciled_resolution(reason_code=RECONCILED_ABSENT)`. A found order becomes ACKED with an `UNKNOWN->ACKED` evidence row.
  - Every failure keeps UNKNOWN and restarts the count: probe error or indeterminate answer, failed or unreadable position / open-orders read, non-zero position, open order on the symbol (also when the probe said not found: a conflicting read), missing, naive or failing GTD lookup, a journal write that fails, a failing finalization. Nothing exits SAFE_MODE; `UNRESOLVED_EXECUTION_INTENT` is entered while anything stays UNKNOWN; an unreadable store enters `DB_FAILURE` and re-raises. The count lives in memory, so a restart starts at zero.
  - `resolve_unresolved_intents`: the young-absent REJECTED branch is gone for ENTRY (SENT and UNKNOWN stay UNKNOWN). An INTENDED ENTRY is probed once: not found goes to REJECTED / `NEVER_SENT` through `finalize_reconciled_resolution`, found goes UNKNOWN then ACKED, anything else UNKNOWN. A protective leg is rejected for absence only when its plan's ENTRY row is REJECTED and the leg is younger than the lookup window (F5); an unreadable ENTRY row counts as not REJECTED. `lookup_window` is used only there.
  - Module docstring resolution table rewritten.
- `src/domain/stream_records.py`: `EXIT_EVIDENCE_ENTITY_TYPES` gains `"EXECUTION_INTENT"` (additive; the error text names the three types).
- No method whose name starts with `place_` or `cancel_` is called in `intent_recovery.py` (AST test). The adapter Protocol stays two probes plus two read-only snapshots.

## Verification actually run (only this plan's tests)

- `uv run pytest -m "not docker" tests/test_intent_recovery_unknown_entry.py tests/test_intent_recovery.py tests/test_stream_records.py` : 111 passed.
- `TRADING_CI_STRICT=1 uv run pytest -m "not docker" tests/test_intent_recovery_pg.py` : 16 passed, none skipped (local PostgreSQL through the harness template database).
- Also run because they touch the two changed modules: `tests/test_phase18_gate.py tests/test_paper_shadow_isolation.py tests/test_persistence_exit_evidence_pg.py tests/test_userdata_router.py tests/test_userdata_replay.py tests/test_domain_no_float.py tests/test_agents_md.py` : 190 passed, 2 failed, both outside this plan (see Deferred Issues).
- `uv run ruff check`, `uv run ruff format --check` (685 files), `uv run mypy src` (219 files), `uv lock --check`, `uv run python scripts/verify_decision_alignment.py all` (ALL_PASS): clean. `git diff --exit-code -- pyproject.toml uv.lock` exits 0 (T-20-SC, no package added).
- The full suite was not run (orchestrator).
- Evidence labels: executed tests with fakes and local PostgreSQL. Binance id visibility is [DOC]. Phase 19 assumption A2 (a GTD expiry is terminal) stays [NOT_TESTED]. Nothing is [DEMO]; no Binance or Telegram call was made.

## TDD record

Task 2 (tracer): RED `bbc24085` (collection ImportError of `EVENT_UNKNOWN_ENTRY_PROBE` for the new test module, and `test_an_execution_intent_has_unknown_exits_too` failing with `entity_type must be ORDER or POSITION`, both seen before the GREEN commit), GREEN `8096b957`. Tracer feedback gate: the plan's `<verify>` command was re-run on the proven slice before Task 3 and passed; no `blocking-human` gate is attached to the tracer, nothing else was asked.
Task 3: RED `b818f91a` (14 resolver and recovery tests failing in `tests/test_intent_recovery_unknown_entry.py`, 3 rewritten tests in `tests/test_intent_recovery.py`, 2 in `tests/test_intent_recovery_pg.py`, all seen failing before the GREEN commit), GREEN `11daacf3`. No REFACTOR commit.
Note: the Task 2 GREEN implementation was deliberately minimal (the protocol and the probe-indeterminate case); the exception handling around reads, GTD lookup, journal and store writes was added in Task 3 GREEN, so the Task 3 RED tests for those cases failed first.

## Deviations from Plan

**1. [Rule 1 - pinned tests] Existing tests pinned the removed 3-day ENTRY rule; assertions rewritten (F-604-style, each docstring names D-11 / Q5)**
- `tests/test_intent_recovery.py`:
  - `test_absent_at_exactly_three_days_stays_unknown_and_just_under_is_rejected` replaced by `test_stop_loss_of_a_rejected_entry_at_exactly_three_days_stays_unknown` (the 3-day window now exists only for protective legs of a REJECTED entry) and `test_an_absent_sent_entry_is_never_rejected_whatever_its_age`.
  - `test_lookup_window_is_a_keyword_argument` now uses a STOP_LOSS leg of a REJECTED entry (name unchanged, meaning unchanged: the window is a keyword argument).
  - `test_resolved_and_unresolved_mix_is_reported_deterministically`: the absent SENT entry is now unresolved and SAFE_MODE is entered (expected report changed accordingly).
  - `test_entry_intended_but_never_sent_becomes_rejected` additionally asserts `resolution_reason_code == NEVER_SENT`; module docstring updated.
- `tests/test_intent_recovery_pg.py`: `test_crash_after_entry_sent_with_the_order_absent_is_rejected` became `test_crash_after_entry_sent_with_the_order_absent_stays_unknown` (the SENT entry stays UNKNOWN, the approval stays consumed, no placement); new `test_crash_after_consume_with_the_order_absent_is_rejected_as_never_sent`, `test_the_unknown_entry_protocol_closes_on_postgres` and `test_the_unknown_entry_protocol_keeps_unknown_when_a_position_exists`.
- Files modified: tests/test_intent_recovery.py, tests/test_intent_recovery_pg.py. Commit: b818f91a.

**2. [Rule 2 - hardening] GTD time validated; fixed keep reasons**
- The plan lists "entry_good_till returns None" as a keep condition; the resolver also treats a naive or non-UTC value and an exception from the callable as an unknown GTD time (`GTD_UNKNOWN`), so a bad value can never satisfy GTD plus grace. Files: src/execution/intent_recovery.py. Commit: 11daacf3.

**3. [Process] Branch-name allow-list of the commit protocol not applied**
- The executor's pre-commit allow-list (`agent-*` branch names) was not applied: the orchestrator pinned the worktree branch `p20-10`; the toplevel and branch were verified before every commit instead.

Otherwise the plan was executed as written. The N = 3 / 5000 ms suggestion is not in code, tests or config.

## Deferred Issues (out of scope, not fixed)

- `tests/test_phase18_gate.py::test_invariant_6_placement_is_single_attempt_and_decides_on_no_message_text` fails on `src/execution/manager.py:2018: str(failed_lost) outside a logger call`. This plan does not touch `manager.py`; observed, not caused by this plan.
- `tests/test_persistence_exit_evidence_pg.py::test_persistence_module_map_lists_every_module` fails because the module map lacks `safe_mode_store` (a `src/persistence` module this plan did not touch).
- Not built here (as the plan states): the caller wiring of the resolver into a running process (plan 20-12's optional `unknown_entries` step, G4-029) and the notification of the protection coordinator when an entry is closed RECONCILED_ABSENT (plan 20-24 register). `entry_good_till` is a constructor callable; the caller supplies it.
- The probe count, spacing and grace stay `NOT_CONFIGURED` in `config/execution/execution-limits-v1.toml` (owner decision O-G, after Demo evidence).

## Known Stubs

None.

## Threat Flags

None. T-20-22 (closing on absence alone), T-20-23 (the evidence row precedes the finalization, a journal failure blocks it) and T-20-24 (F5) are mitigated as the plan states; T-20-SC: no dependency added.

## Self-Check: PASSED

Created and modified files exist (`tests/test_intent_recovery_unknown_entry.py`, `src/execution/intent_recovery.py`, `src/domain/stream_records.py`, the three modified test files, this SUMMARY); commits `59c48343`, `bbc24085`, `8096b957`, `b818f91a`, `11daacf3` are on branch `p20-10`; STATE.md, ROADMAP.md, `.planning/config.json`, `.planning/state.json` and `config/execution/execution-limits-v1.toml` are not modified.
