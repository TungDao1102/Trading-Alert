---
phase: 16-paper-runtime-composition
plan: 23
subsystem: paper-runtime / simulated ledger and exposure reservation
tags: [shadow-ledger, reservation, reserve-at-confirm, q-c, journal-only-recovery, capacity-gates, d-17]

requires:
  - phase: 16-paper-runtime-composition
    provides: "16-19 ShadowFillDriver and eligibility_start_for (Q-B confirm-plus-one); 16-11 ConfirmBook and the SHADOW_CONFIRM_* journal events; 16-16 runtime state ports"
  - phase: 14-backtest-engine
    provides: "Ledger and its functions, check_portfolio gates, advance/lifecycle (called unchanged)"
provides:
  - "src/paper/shadow_ledger.py: ShadowLedger (required initial equity, admit/try_register over check_portfolio, risk_inputs, apply_event), ShadowReservations (check, confirm_payload, reserve, release_expired, record_position_opened, sync, load_records, rebuild_from_records), Reservation/PositionRecord/RebuildReport"
  - "src/paper/shadow_confirm.py: optional ReservationPort on ConfirmBook (serialized CONFIRM section, unknown-append reconcile, retry of an incomplete reserve)"
  - "decisions/16-DEC-Q-C.md: option reserve-at-confirm, decided by user, 2026-10-10"
  - "journal events SHADOW_POSITION_OPENED, SHADOW_PLAN_EXPIRED_UNFILLED, SHADOW_RESERVATION_REFUSED (existing journal, no migration, no second store)"
affects: [16-31 SHADOW wiring (builds ShadowReservations, passes it to ConfirmBook, calls sync after each advance_to and release_expired on each tick, calls rebuild_from_records at start), 16-34 runtime configuration (initial equity), 16-35 attribution of a confirmed-but-expired plan]

plan_head_before: 577767b5b88a19ff7d7c4de06bc3fc6020ea766a
plan_head_after: 822992dac45578c7696937c72e9d2542bde13aa1
commits: 6
actuals:
  tokens: 33000
  tasks: 3
  commits: 6

key-decisions:
  - "Q-C (user, 2026-10-10, 'Chon Option reserve-at-confirm', addendum: the reservation expires at the original plan's expiry, no separate TTL): exposure is reserved only when a valid CONFIRM is accepted AND SHADOW_CONFIRMED was journaled. The basis for the timing is this user decision, not D041."
  - "Design A (check before the journal write, reserve after it, both inside one serialized section) over a tentative reserve with rollback: a failed check or a failed journal write never leaves a reservation and never a successful CONFIRM; the later reserve repeats the same pure check on the same state and cannot refuse."
  - "SHADOW_CONFIRMED carries the reservation facts (symbol, direction, sized risk, planned quantity, signal close, plan expiry, confirm instant, Q-B eligibility start) so the journal alone rebuilds a reservation after a crash between the journal write and the reserve."
  - "An append with an unknown commit outcome is reconciled against the journal: the stored event is authoritative (its confirmed_at_utc feeds Q-B), no second append; an unreadable journal fails closed."
  - "Recovery events use ids and payloads derived only from stable data (plan hash, plan expiry, approval id); occurred_at_utc of the release is the plan expiry, never the restart clock."

requirements-completed: []
requirements-advanced: [PAPER-02]

coverage:
  - id: D1
    description: "A confirmed plan's exposure and booked loss feed the next risk inputs exactly as the Phase 14 ledger returns them; initial equity is a required input with no default and no equity literal"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_shadow_ledger.py#test_registered_plan_and_stop_loss_give_the_backtest_risk_inputs"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_ledger.py#test_the_module_contains_no_numeric_equity_literal"
        status: pass
    human_judgment: false
  - id: D2
    description: "Reserve and release points of the user's Q-C rule: nothing at APPROVE, SKIP, CANCEL, APPROVAL_EXPIRED or confirm TTL; reserved at an accepted CONFIRM; released exactly once at the plan expiry; a confirm with no valid fill window reserves nothing"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_shadow_reservations.py#test_confirm_reserves_exposure_and_journals_the_reservation_facts"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_reservations.py#test_expiry_without_a_fill_releases_exactly_once"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_reservations.py#test_a_confirm_with_no_valid_fill_window_creates_no_reservation"
        status: pass
    human_judgment: false
  - id: D3
    description: "Capacity (cluster, aggregate, position count, same symbol) is checked on the current ledger including waiting reservations, for sequential CONFIRMs and a concurrent race"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_shadow_reservations.py#test_two_sequential_confirms_cannot_exceed_the_remaining_capacity"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_reservations.py#test_two_concurrent_reserves_cannot_exceed_the_remaining_capacity"
        status: pass
    human_judgment: false
  - id: D4
    description: "Journal failure paths leave no reservation and no false successful CONFIRM; an unknown append outcome is reconciled against the journal; recovery at every crash boundary loses and duplicates nothing; expiry while offline restores nothing and is recorded once with deterministic ids"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_shadow_reservations.py#test_an_append_with_an_unknown_outcome_is_reconciled_against_the_journal"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_reservations.py#test_crash_after_the_confirm_is_journaled_still_rebuilds_the_reservation"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_reservations.py#test_a_restart_after_the_expiry_restores_nothing_and_records_the_release_once"
        status: pass
      - kind: integration
        ref: "tests/test_paper_shadow_reservations_pg.py#test_expiry_while_offline_is_recorded_once_across_two_restarts"
        status: skipped
    human_judgment: false
  - id: D5
    description: "A fill turns the reservation into one position without double counting; rebuild_from_records equals an uninterrupted run; a hole is annotated and reported, never filled"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_shadow_reservations.py#test_a_fill_turns_the_reservation_into_one_position_without_double_counting"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_reservations.py#test_rebuild_from_records_equals_an_uninterrupted_run"
        status: pass
      - kind: unit
        ref: "tests/test_paper_shadow_reservations.py#test_a_hole_in_the_history_is_annotated_and_reported_never_filled"
        status: pass
    human_judgment: false
---

# Phase 16 Plan 23: Shadow Ledger and Reserve-at-Confirm Summary

SHADOW now sizes against simulated state: a `ShadowLedger` over the Phase 14 ledger (required equity, no default), and a journal-backed reservation lifecycle that follows the user's Q-C rule `reserve-at-confirm`, with recovery from the existing journal alone.

## Task 3 design and acceptance criteria (updated before implementing, per the coordinator)

Recovery contract for plan 16-31, so it never has to assume that SHADOW_POSITION_OPENED alone is enough. `rebuild_from_records` reads every lifecycle event of an approval, correlation `shadow-confirm:<approval_id>`, joined by `plan_hash`:

| Journal evidence | State | Recovery |
|---|---|---|
| SHADOW_CONFIRMED (with `reservation`), nothing else, plan not expired | confirmed, unfilled | restore the reservation (covers the crash between the journal write and the reserve) |
| SHADOW_CONFIRMED + SHADOW_POSITION_OPENED | position | replay `advance` over the minutes from the persisted plan, quantity and eligibility start; exposure and bookings rebuilt; never reserved twice |
| SHADOW_CONFIRMED, nothing else, plan expired (also while offline) | expired unfilled | restore nothing, no late fill, record SHADOW_PLAN_EXPIRED_UNFILLED idempotently |
| any of the above + SHADOW_PLAN_EXPIRED_UNFILLED or SHADOW_RESERVATION_REFUSED | ended | restore nothing |
| a lifecycle event with another plan_hash than the SHADOW_CONFIRMED | conflict | reported, nothing restored |
| SHADOW_CONFIRM_EXPIRED / _CANCELLED (no SHADOW_CONFIRMED) | never reserved | ignored |

Acceptance criteria met by tests in `tests/test_paper_shadow_reservations.py` (the 10 required tests of the first message plus the additions of the later messages): (a) reservation kept before expiry; (b) release exactly once; (c) the 60 s SHADOW_CONFIRM_EXPIRED never touches a reservation; (d) NO_MINUTE_BEFORE_EXPIRY reserves nothing; (e) restart before expiry restores; (f) restart after expiry restores nothing and creates no late fill; (g) fill converts the reservation to the position without double counting; (h) replays create no duplicate reserve, release, fill or exposure; (i) a journal failure is not acknowledged and reserves nothing; (j) competing CONFIRMs (sequential and threaded) cannot exceed capacity; crash before the append, after the append before the reserve, and after the reservation exists; unknown append outcome (reconciled, unreadable journal fails closed, later retry adopts the stored confirm instant); recovery events independent of the restart clock; missing parent row refused; same id with a different payload is a `JournalConflict`; every new event compatible with the fixed-list consumers.

## Accomplishments

- **ShadowLedger** (Task 1 tracer, kept): wraps `src.backtest.ledger.Ledger` by calls only; `admit`/`try_register` run the unchanged `check_portfolio` gates (cluster cap, aggregate cap, position count, daily stop) over `risk_inputs`, which now include still-valid reservations. One exposure per plan, never two.
- **ShadowReservations**: `check` (before the journal write), `reserve` (after it; idempotent on `plan_hash:approval_id`), `release_expired`, `record_position_opened`/`sync`, `load_records`, `rebuild_from_records`.
- **ConfirmBook** (`src/paper/shadow_confirm.py`, minimal seam): optional `reservations=` port; `handle_confirm` runs recheck, capacity check, SHADOW_CONFIRMED write and reserve inside one serialized section; an append whose outcome is unknown is reconciled against the journal; an incomplete reserve is retried by a repeated press; `RecheckFn` may return code text (the engine label `CONFLICT_WITH_OPEN_POSITION` is not a `RejectionReason`).
- **Journal events**: no existing event expressed the end of a confirmed-but-unfilled plan, so three were added to the existing journal (`event_type` is String(64), no CHECK, no migration, no table). None is in `TERMINAL_CONFIRM_EVENTS`; none is accepted as a `confirm_event` by `attribute_shadow_outcome` (it raises "not a terminal confirm event"); `assert_no_stranded_approvals`, `expire_due` and `expire_on_restart` are unaffected (tested).

## Task Commits

1. Task 1 RED: `75ed124` test(16-23) failing ledger tracer tests
2. Task 1 GREEN: `1551750` feat(16-23) ShadowLedger over the Phase 14 ledger
3. Task 2: `03f85f8` docs(16-23) Q-C decision record, reserve-at-confirm, decided by user
4. Task 3 RED: `6dd2ff7` test(16-23) reserve-at-confirm lifecycle tests (the implementation files were reverted to the Task 1 state while the tests were written, and the run confirmed they fail at collection)
5. Task 3 GREEN: `adb2117` feat(16-23) reservations, capacity gates and journal-only recovery
6. `822992d` test(16-23) PostgreSQL journal tests (skip without `TEST_DATABASE_URL`)

(`commits: 6` is measured with `git rev-list --count 577767b..HEAD` before this SUMMARY commit.)

## Deviations from Plan

1. **[Rule 3 - Blocking] Stale worktree base.** The worktree started at 9186194, which lacked this plan and its dependencies. The branch was fast-forwarded to `develop` (`git merge --ff-only develop`, 577767b = `plan_head_before`). Nothing was rewritten.
2. **[Rule 3] `ShadowLedger` takes two more required inputs** (`parameter_set_params`, `started_at_utc`) because `Ledger.start` needs them; `initial_equity` still has no default.
3. **[Coordinator-directed scope] Files beyond `files_modified`:** `src/paper/shadow_confirm.py` (the ConfirmBook seam the coordinator named), `tests/test_paper_shadow_confirm.py` (the `Harness` passes an optional `reservations` argument), and two new test files. `src/backtest` and `src/risk` are unchanged (`git diff 577767b..HEAD -- src/backtest src/risk` is empty).
4. **[Plan Task 3 wording] `rebuild_from_records` is a method of `ShadowReservations`** (it owns the ledger, the journal writer and the held state), and it takes journal events rather than only SHADOW_POSITION_OPENED records, as the ratified recovery contract requires. SHADOW_POSITION_OPENED is written through the existing journal (the `ConfirmStores` ports), not through the runtime-state port: the user's Q-J says every record is a journal event, and the confirm correlation already groups the lifecycle.
5. **[Test-only] The Task 1 AST test** now rejects float literals and non-zero `Decimal(...)` literals instead of every non-zero int, because counters and slice bounds are legitimate (the intent, no equity literal, is unchanged).

## Known limitations and follow-ups (not defects of this plan)

- **Full replay from epoch start.** Equity continuity means every position since the epoch is replayed from the persisted records over 1m history, which must therefore stay available (REST or recorded); a periodic ledger checkpoint would be a later optimisation. Plan 16-31 supplies `minute_source`, `driver_for` and `funding_for`.
- **Fill while offline, expiry while offline.** Per the ratified rule a plan that expired while the process was down is recorded unfilled and never revived, even if price touched the entry before the expiry.
- **Order of calls in 16-31.** `sync` must run after each `advance_to` and before `release_expired` on the same tick, so a fill is journaled before an expiry sweep can release it.
- **Attribution of a confirmed-but-expired plan** (`assemble_paper_record` expects order and fill for a user-executed-sim outcome) is plan 16-35's concern; the terminal event to map is `SHADOW_PLAN_EXPIRED_UNFILLED` with reason `PLAN_EXPIRED_UNFILLED`.
- **A defensive refusal** after SHADOW_CONFIRMED (never expected inside the serialized section) is journaled as SHADOW_RESERVATION_REFUSED and the press is reported as not confirmed; the in-memory confirm entry stays CONFIRMED, recovery honours the refusal event.
- **PostgreSQL tests are unverified locally:** `tests/test_paper_shadow_reservations_pg.py` skipped (no `TEST_DATABASE_URL`). The JournalConflict, ParentRowMissing and idempotent-replay rules are exercised against a faithful in-memory model (`FaultyStores`) and the PG tests run in CI.
- **Pre-existing failure, not caused here:** `tests/test_cost_parity.py::test_simulator_and_paper_call_evaluate_risk_with_identical_arguments` (list vs tuple for `open_positions`), already logged in `deferred-items.md` by plan 16-15. All other `-m "not docker"` tests pass.

## Verification

- `uv run pytest -m "not docker"`: all pass except the one pre-existing failure above.
- `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src` (170 files): clean.
- Ledger tracer, reservation and PG test files: 12 + 42 passing, 3 PG tests skipped.

## Known Stubs

None. `basis_for` (the sized risk and planned quantity of the signal bar) and `driver_for`/`funding_for` are injected seams that plan 16-31 binds; they are not stubs in this plan.

## Threat Flags

None new. T-16-53 (equity) mitigated: required input, no default, AST test. T-16-54 (lost positions after restart) mitigated: journal-only recovery, deterministic events, equivalence test. No package install, no network.

## Self-Check: PASSED

Created files found: `src/paper/shadow_ledger.py`, `tests/test_paper_shadow_reservations.py`, `tests/test_paper_shadow_reservations_pg.py`, `.planning/phases/16-paper-runtime-composition/decisions/16-DEC-Q-C.md`. Modified: `src/paper/shadow_confirm.py`, `tests/test_paper_shadow_confirm.py`, `tests/test_paper_shadow_ledger.py`. Commits 75ed124, 1551750, 03f85f8, 6dd2ff7, adb2117, 822992d exist on the branch.
