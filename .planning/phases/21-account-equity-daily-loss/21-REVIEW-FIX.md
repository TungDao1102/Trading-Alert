---
phase: 21-account-equity-daily-loss
fixed_at: 2026-10-25T00:00:00Z
review_path: .planning/phases/21-account-equity-daily-loss/21-REVIEW.md
iteration: 1
findings_in_scope: 10
fixed: 9
skipped: 1
status: partial
---

# Phase 21: Code Review Fix Report

**Fixed at:** 2026-10-25
**Source review:** `.planning/phases/21-account-equity-daily-loss/21-REVIEW.md`
**Iteration:** 1
**Scope:** Warnings WR-01 to WR-10 (there was no Critical finding; Info IN-01 to IN-09 were out of scope)

**Summary:**
- Findings in scope: 10
- Fixed: 9 (WR-10 partly: the PLACED exit only, the operator reason is left to the owner)
- Skipped: 1 (WR-05, needs the owner; only its documentation fallback was applied)
- Needs owner (also listed under Skipped or Fixed below): WR-05, the operator release reason of WR-10

**Where the tests ran:** the isolated worktree `.claude/worktrees/agent-a631a3571d0cfb6d1`, branch
`worktree-agent-a631a3571d0cfb6d1`, with `TEST_DATABASE_URL` set, so the `*_pg.py` files ran (they did
not skip). Only the test files of the touched modules plus `tests/test_decision_alignment_bookkeeping.py`
were run (755 passed, `-n 4`), `ruff check` on `src` and the touched tests, `mypy` on the 8 touched
source files, and `scripts/verify_decision_alignment.py all` (ALL_PASS). The full suite was not run,
as instructed. The worktree branch was first fast-forwarded to `develop` (`f25d89ce`), because the
review and the Phase 21 code were not in the commit the worktree was created from.

**No migration was needed or added.** No `params/**/*.toml`, no `config/` file and no
`.planning/state.json` was touched. No new default for an owner-chosen number was introduced.

## Fixed Issues

### WR-01: A held or just-derived DAILY_STOP is dropped to a state-less NO_TRADE on a store error

**Status:** fixed (logic: requires human verification)
**Files modified:** `src/execution/day_risk_service.py`, `tests/test_day_risk_service.py`
**Commit:** `159eb1f7`
**Applied fix:** Reproduced first (latched day plus `list_components` failure returned state `None`).
`evaluate` now reads the latch before the components: with the latch held an unreadable components
read keeps the verdict DAILY_STOP with an unknown loss (`loss_quote None`); without the latch it still
blocks (`DAY_STATE_UNREADABLE`). A newly derived stop whose `latch_stop` write fails now keeps the
DAILY_STOP verdict (the caller cancels entries, which only reduces risk), the stop is held in process
(`_unpersisted_stops`, so a later gain cannot lift it) and the write is retried on the next call with
the first failure time. This reverses the earlier test that pinned "failing latch write is blocked";
that test was rewritten.
**Tests:** `test_a_latched_day_with_unreadable_components_still_answers_daily_stop`,
`test_an_unlatched_day_with_unreadable_components_still_blocks`,
`test_a_failing_latch_write_still_answers_daily_stop_and_the_next_call_latches`,
`test_an_unpersisted_stop_holds_in_process_when_the_loss_falls`.

### WR-02: The approval serialisation lock is a per-UTC-day row

**Status:** fixed (logic: requires human verification)
**Files modified:** `src/persistence/risk_reservations.py`, `tests/test_risk_reservation_approval_pg.py`
**Commit:** `564a8b20`
**Applied fix:** `reserve_in` takes `pg_advisory_xact_lock(APPROVAL_SERIALISATION_LOCK_KEY)` before the
per-day `daily_risk_days` row lock. The key is the first 8 bytes of
SHA-256("trading-alert:risk_reservations:approval-serialisation") with the top bit cleared (same
derivation as the paper instance lease keys), released by PostgreSQL at commit or rollback. No
migration. Reproduced first: two approvals with `acted_at` 23:59:59.9 and 00:00:00.1 both passed a
cap that allows one. The existing two-connection race test was refactored into a helper and its lock
monitor now also recognises the advisory-lock wait.
**Tests:** `test_two_approvals_acted_on_either_side_of_midnight_still_serialise` (PG),
`test_the_approval_serialisation_lock_key_is_the_documented_stable_63_bit_key`, and the unchanged
`test_two_concurrent_approvals_that_only_one_fits_cannot_both_pass`.

### WR-03: The manager sizes from a caller-supplied account_state and never compares it with the live equity

**Status:** fixed (logic: requires human verification)
**Files modified:** `src/execution/manager.py`, `tests/test_execution_manager.py`
**Commit:** `31b4a7f7`
**Applied fix:** New gate 5f3 in `execute_approved_plan`, after the margin guard passes and before the
hand-off record and the consume: if `risk_kwargs["account_state"].equity` (which sized the quantity)
is greater than `guard_verdict.equity_used` (the fresh, age-checked equity of the same call), the
outcome is NO_TRADE `UNCERTAIN_ACCOUNT_STATE`. Equal or smaller passes (it sized conservatively). The
reviewer's second option (accept only a `LiveRiskInputs` object) was not taken: it changes the
manager signature, which Phase 24 composes. Note the existing quantity-above-approved gate already
catches an inflated equity that sizes above the approved quantity; the new gate covers a stale figure
that still sizes within it. Red confirmed by removing the gate.
**Tests:** `test_gate_5f3_refuses_a_sizing_equity_above_the_live_equity_the_guard_read`,
`test_gate_5f3_passes_a_sizing_equity_equal_to_or_below_the_live_equity` (3 cases).

### WR-04: build_live_risk_inputs ignores the day's latch and has no freshness or "is today" check

**Status:** fixed (logic: requires human verification)
**Files modified:** `src/execution/live_risk_inputs.py`, `tests/test_live_risk_inputs.py`, `tests/test_live_risk_parity.py`
**Commit:** `520d4544`
**Applied fix:** `build_live_risk_inputs` takes two required keyword arguments, `now_utc` and
`max_equity_age` (no default: the live value is the owner's `account.max_equity_age_ms`). A day row
whose `stop_latched_at_utc` is set gives `DAILY_STOP_BLOCK` even with a verdict computed before the
latch; a day row that is not `utc_day_of(now_utc)` gives UNCERTAIN; an equity reading older than the
bound or future-dated (age equal to the bound passes) gives UNCERTAIN; a naive clock or a non-positive
bound raises `ValueError`. Limit: the verdict has no timestamp, so a verdict of an earlier tick on the
same day cannot be detected here; the latch (carried by the day row) is the sticky part. Documented in
the module docstring.
**Tests:** `test_a_latched_day_row_blocks_even_with_a_verdict_computed_before_the_latch`,
`test_yesterdays_day_row_and_verdict_are_not_todays_inputs`,
`test_the_equity_age_is_rechecked_with_the_owner_bound` (6 cases),
`test_the_builder_refuses_a_naive_clock_and_a_non_positive_age_bound`.

### WR-06: The "late open is over-counted at worst" claim is wrong for a day that started with a gain

**Status:** fixed (logic: requires human verification; behaviour change for the caller)
**Files modified:** `src/risk/daily_loss.py`, `src/execution/day_risk_service.py`, `tests/test_day_risk_service.py`, `tests/test_daily_loss.py`, `tests/test_day_risk_stream.py`
**Commit:** `3dda2f15`
**Applied fix:** The claim was verified as wrong for a gain day (threshold is r times the larger
equity of the moment). `DailyLossResult` gains `net_pnl_upper_quote` (the day's signed result taking
the most favorable amount per fill, the opposite of `loss_quote`). When a day is opened, the base is
`equity now - net result` if the net result is a gain; after a loss the smaller moment equity is kept
(conservative). To know the net result the day is opened only after a backfill of the current
generation has completed for it; otherwise `BLOCKED_DAY_BASE_UNAVAILABLE` and no equity read. A base
that would be zero or negative is refused. **Behaviour change the Phase 24 composition must respect:**
call `backfill` before the first `evaluate` of a UTC day (including the rollover at 00:00); an
`evaluate` first answers `DAY_BASE_UNAVAILABLE` and the next tick succeeds. Ten existing tests that
used `evaluate` to open a day with an unknown loss were adapted (`preopen` helper, a backfill first,
or a clean first cycle); their intent is unchanged. This follows the reviewer's "exact" option; it
also does not weaken the D-08 rule (the fresh in-day equity read is still required).
**Tests:** `test_a_late_open_after_a_morning_gain_derives_the_day_start_base`,
`test_a_late_open_after_a_morning_loss_keeps_the_conservative_base_of_the_moment`,
`test_a_morning_gain_uses_the_most_favorable_amount_when_sources_diverge`,
`test_opening_a_day_without_a_current_backfill_is_blocked_and_reads_no_equity`,
`test_a_stream_gap_before_the_open_makes_the_base_unavailable_until_a_backfill`,
`test_a_gain_larger_than_the_equity_cannot_make_a_base`,
`test_the_favorable_net_pnl_takes_the_largest_amount_per_fill`,
`test_the_favorable_net_pnl_is_signed_and_unknown_with_the_loss`.

### WR-07: Failed, unverified and unmatched DAILY_STOP cancels emit no alert; the alert failure is swallowed

**Status:** fixed
**Files modified:** `src/execution/daily_stop.py`, `tests/test_daily_stop.py`
**Commit:** `c3042f12`
**Applied fix:** On a DAILY_STOP verdict, `enforce_daily_state` now alerts on every call that finds a
refused or unverified cancel (reason `ENTRY_CANCEL_INCOMPLETE`) or an unmatched system entry (reason
`UNMATCHED_ENTRY_ORDER`), under the existing `DAILY_STOP` event. The sink dedupes by
(event, subject, reason), so the one-shot stop alert does not hide them and a repeat inside the window
is only counted. No new event: `ALERT_EVENTS` and the OPS-05 matrix are unchanged. A sink exception is
no longer silent: `DailyStopOutcome.alerts_failed` lists `(event, exception class name)` (new field with
a default, existing constructions still work). The one-shot stop alert is still not re-sent by this
pure function when the sink raised before queuing; the caller must log `alerts_failed` (documented).
**Tests:** `test_a_clean_cancel_alerts_the_stop_once_and_nothing_about_the_cancel`,
`test_an_incomplete_cancel_is_alerted_again_on_every_call_while_the_latch_holds`,
`test_an_unmatched_system_entry_on_a_stopped_day_is_alerted`,
`test_the_real_sink_does_not_dedupe_the_incomplete_cancel_into_the_stop_alert`, and three existing
tests plus `test_a_failing_alert_sink_does_not_undo_the_cancels` updated.

### WR-08: One missing prior day plus an open position blocks the day permanently

**Status:** fixed (logic: requires human verification; interprets D-08)
**Files modified:** `src/persistence/day_risk.py`, `src/execution/day_risk_service.py`, `src/risk/daily_loss.py`, `tests/support/day_risk_fakes.py`, `tests/test_day_risk_service.py`, `tests/test_daily_loss.py`, `tests/test_day_risk_pg.py`
**Commit:** `28104c7a`
**Applied fix:** Reproduced first (two-day gap with exposure stayed `DAY_STATE_MISSING`). New store
method `has_earlier_day(utc_day)` (primary-key range query, no migration); the service passes it to
`day_open_action`, whose parameter is renamed `previous_day_present` to `earlier_day_present`. Any
stored day before today now lets the day open from a fresh in-day equity read even with exposure; a
store that never held a day still blocks, and a row of a later day does not count. D-08 says "the
rollover from a persisted previous day"; this reads "previous" as "any earlier", as the reviewer
proposed (D-08 also requires the fresh REST read, which is kept). Flagged here because it relaxes a
D-07 block.
**Tests:** `test_a_two_day_gap_with_exposure_opens_from_a_fresh_read`,
`test_a_later_day_row_is_not_an_earlier_day` (2 cases),
`test_has_earlier_day_is_true_for_any_stored_day_before_and_false_otherwise` (PG), the
`day_open_action` table test with the renamed argument.

### WR-09: The REST backfill covers only the configured symbols and only FUNDING_FEE

**Status:** fixed (logic: requires human verification; partial by design)
**Files modified:** `src/execution/day_risk_service.py`, `tests/support/day_risk_fakes.py`, `tests/test_day_risk_service.py`
**Commit:** `aa11e9f0`
**Applied fix:** `backfill` also reads the whole-account `REALIZED_PNL`, `COMMISSION` and
`INSURANCE_CLEAR` income (three more paged calls; the reader port is generic, the adapter is
unchanged). A row of a symbol outside the configured ones, an account-level row with no symbol, or any
`INSURANCE_CLEAR` row makes the loss unknown (`last_error_type` is `IncomeOutsideConfiguredSymbols`)
instead of understated; a later clean backfill makes it known again. The reviewer's equality check
(income totals against folded fills) was not built: its semantics (rounding, commission asset, rebates)
are unverified on mainnet and a false mismatch would stop trading for the day; the limit is stated in
the module docstring. The fake reader gained `income_by_type` (the old `income` argument is now the
FUNDING_FEE answer only). Cost: 3 extra income reads per backfill (rate-limit weight, to be sized in
Phase 24).
**Tests:** `test_a_loss_row_the_fold_cannot_see_makes_the_loss_unknown` (4 cases),
`test_loss_rows_of_the_configured_symbols_do_not_disturb_the_known_loss`, and the reader-call-list test
extended.

### WR-10: The release table can leave counted risk with no exit

**Status:** fixed partly (PLACED exit done; operator reason needs owner and a migration)
**Files modified:** `src/risk/reservations.py`, `tests/test_risk_reservations.py`, `tests/test_risk_reservations_pg.py`
**Commit:** `0c93be50`
**Applied fix:** `RELEASE_SOURCE_STATUSES[POSITION_CLOSED]` is now `{PLACED, OPEN}` (a closed position
implies its entry filled; when `mark_open` was missed the row stayed PLACED and counted). No migration:
the reason is already in the CHECK of migration 0011. Red confirmed on the PG store (`RowConflict`).
Not done: the `OPERATOR_RELEASED` reason. It needs a new CHECK value (migration 0013, and migration
pins kept consistent with the Phase 22 worktree) and an operator path to call it, which is a design
and owner decision.
**Tests:** `test_a_closed_position_releases_a_placed_row_whose_first_fill_was_never_marked` (PG), the
two release-table oracles updated.

## Skipped Issues

### WR-05: A "known" daily loss never expires by time

**File:** `src/execution/day_risk_service.py:285-287` and `:466-469`
**Reason:** needs-owner. The fix is an age bound for the loss, i.e. a new owner-chosen number (the
review itself says "from an owner key, NOT_CONFIGURED until the owner decides"). Adding the key would
also add one more `NOT_CONFIGURED` limit to `config/execution/execution-limits-v1.toml`, which blocks
the live path until set. No key and no default was added. Only the reviewer's "at minimum" fallback was
done, in commit `70cb6502`: `current_daily_loss_quote` now states that a known loss has no age bound
and that freshness is delegated to the Phase 20 feed checks and to the caller (run `backfill` on a
schedule and after a gap). The Phase 24 composition should also run `backfill` periodically.
**Original issue:** After one successful `backfill`, the loss stays "known" until an invalidation; a
fill the stream never delivers and that raises no gap leaves it understated for the rest of the day.

## Notes for the orchestrator

- Files also likely touched by the Phase 22 fixer: `src/execution/manager.py` (WR-03 adds gate 5f3
  right after the margin guard block, about 17 lines before `# Gate 5g`, and nothing else) and
  `tests/test_execution_manager.py` (two tests added before
  `test_a_plain_string_refusal_code_passes_through_unchanged`). `src/persistence/risk_reservations.py`
  is also near the Phase 22 margin-claim code (`list_margin_claims`, migration 0012): WR-02 only adds a
  constant, an import and one `session.execute` line in `reserve_in`.
- No migration was added; no migration pin changed. Migration 0013 would be needed only for the
  deferred `OPERATOR_RELEASED` reason (WR-10) or for the Info items IN-01 and IN-02.
- The composition (Phase 24) must pass `now_utc` and `max_equity_age` to `build_live_risk_inputs`
  (WR-04) and call `backfill` before the first `evaluate` of each UTC day (WR-06).

---

_Fixed: 2026-10-25_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
