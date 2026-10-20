---
phase: 19-execution-plan-binding-price-check
fixed_at: 2026-10-20T10:05:00Z
review_path: .planning/phases/19-execution-plan-binding-price-check/19-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 4
skipped: 0
status: all_fixed
---

# Phase 19: Code Review Fix Report

**Fixed at:** 2026-10-20T10:05:00Z
**Source review:** .planning/phases/19-execution-plan-binding-price-check/19-REVIEW.md
**Iteration:** 1

**Scope:** the owner restricted this run to CR-01, CR-02, CR-03 and WR-02. Every other finding
is listed under "Skipped Issues" as an owner decision.

**Summary:**
- Findings in scope: 4
- Fixed: 4 (CR-01 and CR-03 change safety logic: please confirm them by hand)
- Skipped (owner decision): WR-01, WR-03, WR-04, WR-05, WR-06, WR-07, IN-01..IN-06

## Fixed Issues

### CR-01: The mark-price age was measured against a `now_utc` taken before the read

**Status:** fixed: requires human verification (safety logic)
**Files modified:** `src/execution/live_context.py`, `src/execution/manager.py`,
`src/execution/pre_placement.py`, `src/adapters/binance_usdm.py` (docstring only),
`scripts/demo_rehearsal.py`, `tests/test_execution_manager.py`, `tests/test_pre_placement.py`
**Commit:** 3da4fe88
**Applied fix:**
- `LivePlacementContext` has a new required field: an injected `clock`, checked to be callable.
- The manager reads that clock once, after all gate 5e live reads. A clock that raises or returns
  a naive time counts as "not available" and refuses.
- The reading is passed in as `PrePlacementInputs.mark_checked_at_utc`, and `check_mark_price`
  measures the age at that instant.
- A reading may be stamped up to `max_clock_skew` ahead of the check instant and still count as
  age zero. That bound is the existing ratified drift margin `gtd_clock_margin`, so no new number
  was introduced.
- These readings still refuse with MARK_PRICE_UNAVAILABLE:
  - a reading stamped further ahead than that
  - a reading older than `max_mark_price_age_ms`
  - a missing check instant
- The demo rehearsal passes its own `ctx.clock`.
- I did not edit `config/execution/execution-limits-v1.toml` or `docs/DECISIONS.md`.

**Tests changed (they encoded the bug):**
- `tests/test_execution_manager.py`: the fake stamped its default reading BEFORE `now_utc`
  (`now_utc - mark_age_ms`). It now stamps it 250 ms AFTER `now_utc`, and the context clock reads
  `mark_age_ms` later than that.
- The `stale`/`future` mark cases are now measured against the post-read clock.
- `test_live_context_validates_every_field` now covers the new `clock` field.
- The purity allowlist gained `collections.abc` (stdlib, used for the clock type).

**New regressions:**
- `test_mark_age_a_fresh_mark_stamped_after_now_utc_places`: the mark is stamped 3 s after
  `now_utc` and the clock reads 1 s later. The test also asserts that the clock was read after
  the live reads.
- `test_mark_age_staleness_is_measured_at_the_post_read_clock`
- `test_mark_age_an_unreadable_clock_refuses`
- `test_evaluate_mark_age_*` and `test_check_mark_price_tolerates_only_the_bounded_clock_skew`

All of these fail on the pre-fix code.

### CR-02: The Demo rehearsal's `far`/`fill` scenarios could never pass gate 5e

**Status:** fixed
**Files modified:** `scripts/demo_rehearsal.py`, `tests/test_demo_rehearsal_flow.py`
**Commit:** 002a1a4e
**Applied fix:**
- `derive_plan` now builds a real zone that contains the derive-time mark.
- On the near side the zone reaches past the mark by `MARK_ZONE_CUSHION_RATE = 0.005`. This is a
  named rehearsal constant, not a strategy parameter.
- The far side is mirrored, so the zone mid (the price the manager places at) is still exactly
  the far/fill entry.
- The stop is now anchored below `entry_min`, as the binding requires.
- The back-solved rehearsal equity uses the adverse sizing edge `entry_max`, matching
  `size_and_quantize`.
- The production `check_mark_price` zone rule is unchanged.

**Tests changed:**
- `run_flow` and `test_enablement_is_in_process_only` no longer force the fake mark onto the
  entry.
- The derivation oracle was re-derived by hand, with the arithmetic in the test comments:

  | Value | Was | Now |
  |---|---|---|
  | far zone | 58500.0 (single price) | 56700.0-60300.0 |
  | stop | 57622.5 | 55849.5 |
  | equity | 766.96 | 3625.09 |

  The fill zone is 59700.0-63300.0.

**New regressions:**
- `test_derived_zone_contains_the_mark_and_its_mid_is_the_entry` runs the production
  `check_mark_price` and `check_snapped_geometry`.
- `test_order_scenarios_reach_the_entry_against_the_fakes_own_mark[far|fill]`
- `test_a_mark_past_the_zone_cushion_is_still_refused`: the production gate is not weakened.

**Not done:** the rehearsal was not run with `--execute` and there was no network access. It is
verified offline only.

### CR-03: One zero position read declared FLAT and swept every leg

**Status:** fixed: requires human verification (safety logic)
**Files modified:** `src/execution/protection.py`, `src/execution/emergency_close.py`,
`tests/support/protection_doubles.py`, `tests/test_emergency_market_close.py`,
`tests/test_protection_branches.py`, `tests/test_protection_take_profits.py`
**Commit:** f8773d9c
**Applied fix:**
- In the coordinator, a FLAT transition now needs a second, fresh `snapshot_positions` read that
  is also zero (`_second_read_is_flat`, the T-8-30 rule). This applies in four places:
  `_attach_take_profits`, `_watch_exit`, `_on_stop_lost` and `_on_no_position_on_stop`.
- If the second read is not zero, the coordinator journals `PROTECTION_REST_FAILED` /
  `TransientPositionGap` and keeps the current state. An unreadable second read never counts as
  flat.
- `MarketEmergencyCloser.close_position` confirms both of its "flat" answers (already flat at
  the start, and flat after a part) the same way.
- In the closer, a zero read followed by a non-zero one fails closed: code
  `TRANSIENT_POSITION_GAP`, SAFE_MODE, a critical alert, and the method returns False. No further
  part is sent in that call; the coordinator's next step starts again from fresh reads.
- The deadlines are unchanged.

**Tests changed:**
- In `test_a_position_above_the_market_maximum_closes_in_three_parts`, the expected call order
  gains the confirming `snapshot_positions` read.

**New regressions:** these use the shared helper `script_empty_position_reads`, which returns a
transient empty answer without changing the fake's state.
- Empty read followed by the real position in PROTECTED: the ACTIVE stop is kept and the plan
  later reaches COMPLETE.
- The same case in COMPLETE: all three legs are kept.
- `_on_stop_lost` with a terminal entry: no FLAT and no sweep.
- `-4509` with a terminal entry: the plan stays UNPROTECTED (blocking) and the stop is
  re-placed.
- Closer, empty first read: nothing is sent and the close fails closed.
- Closer, empty read after a part: no further send and the close fails closed.
- Positive controls: a genuine exit or flat still ends FLAT after exactly two zero reads.

All of these fail on the pre-fix code.

**Interaction with WR-04 (not fixed here):** in the `_on_stop_lost` gap case:
- The entry is terminal and the plan stays in PROTECTED_ENTRY_OPEN.
- On the next step the stop is not read again, so the plan settles to PROTECTED.
- It then attaches TPs with the stop still non-ACTIVE.

This is the same outcome the old code reached for an unreadable position read. Before the fix,
this path declared FLAT and cancelled every leg of an open position. The test pins only "never
FLAT, never swept". How a lost stop is escalated is still WR-04, an owner decision.

**Choice for the owner to confirm:** when the closer's first read is zero but the confirming read
is not, it fails closed without sending. The alternative is to continue the close from the
second read. I chose not to add a new send path.

### WR-02: The same-symbol position check trusted the caller's list

**Status:** fixed
**Files modified:** `src/execution/manager.py`, `src/execution/pre_placement.py`,
`tests/fixtures/phase9/placement_sequences/expected.json`, `tests/test_execution_manager.py`,
`tests/test_pre_placement.py`, `tests/test_execution_exactly_once_pg.py`,
`tests/test_approval_replay_pg.py`
**Commit:** 7c9f4b2b
**Applied fix:**
- Gate 5e now also reads `adapter.snapshot_positions(symbol=bound.symbol)`; `snapshot_positions`
  was added to the `ExecutionAdapter` Protocol.
- `position_symbols` is the set of symbols from the live rows plus the caller's reconciled list.
- A row counts as a position unless its amount is a Decimal zero. A row with no symbol counts as
  on the placed symbol.
- If the read raises or returns something other than a list, `position_symbols` is `None`, which
  refuses with SYMBOL_STATE_UNAVAILABLE. `check_symbol_free` and `PrePlacementInputs` accept
  `None` for this.

**Tests and fixture changed:**
- The fake adapter gains `snapshot_positions`.
- `PRE_PLACEMENT_READS` gains the new read.
- `tests/fixtures/phase9/placement_sequences/expected.json`: the golden `method_sequence` gains
  one entry, `snapshot_positions`. I edited this list by hand: no generator script exists for
  this fixture and the 19-13 and 19-15 commits also edited it by hand.
- Three PG negative controls filled the first entry and expected a second placement when no
  durable intent row exists:
  - `test_negative_control_never_remembering_store_places_two_entries`
  - `test_negative_control_never_remembering_store_places_two_entries_after_free[filled]`
  - `test_negative_control_a_store_that_never_remembers_places_two_entries`

  The new live read now blocks that second entry by itself. These tests now flatten the fake
  position before the second call, so they still isolate the durable-intent guard.

**New regressions:**
- `test_wr02_a_live_position_on_the_symbol_refuses_with_an_empty_caller_list` covers a long
  position, a short position, an unreadable amount and a row with no symbol.
- `test_wr02_an_unreadable_position_read_refuses_fail_closed`
- `test_wr02_a_flat_row_or_another_symbol_does_not_block`
- `test_check_symbol_free_unreadable_positions_refuse`

All of these fail on the pre-fix code.

## Skipped Issues

All of the following were skipped as owner decisions. The owner kept these out of this run's
scope because they change placement or protection semantics, or need a decision.

### WR-01: The approved quantity is not covered by the plan hash
**File:** `src/execution/binding.py:179`
**Reason:** skipped: owner decision. A storage or binding design change (D051 c freezes the hashed
field set).
**Original issue:** `quantity_after_rounding` from the caller's TradePlan is trusted as the
approved bound.

### WR-03: The emergency close can over-close
**File:** `src/execution/emergency_close.py:361-365, 393-395`
**Reason:** skipped: owner decision. It depends on how Q5 reasoning applies to closes.
**Original issue:**
- An ACK is counted as CLOSED.
- `found=False` right after an ambiguous error triggers a new send.

### WR-04: A lost stop while the entry is open is not blocking or escalated
**File:** `src/execution/protection.py:986-990, 1027-1039`
**Reason:** skipped: owner decision. It needs new blocking and SAFE_MODE rules. See the CR-03
interaction note above.
**Original issue:** `_on_stop_lost` does nothing when the position is unreadable or when the
position is flat while the entry is still open.

### WR-05: An ENTRY_STATE_UNKNOWN entry is never handed to the coordinator
**File:** `src/execution/manager.py:1045-1061`
**Reason:** skipped: owner decision. It changes protection semantics.
**Original issue:** a resting GTD entry that fills after an UNKNOWN placement gets no stop.

### WR-06: MARK_PRICE_OUTSIDE_ZONE refuses the resting-limit case
**File:** `src/execution/pre_placement.py:278-286`
**Reason:** skipped: owner decision. It depends on what D-05 means. CR-02 was fixed without
relaxing this rule.
**Original issue:** a LONG with the mark above the zone is refused in both directions.

### WR-07: D-22 sized risk never reaches analytics
**File:** `src/analytics/live_outcomes.py:121-144`
**Reason:** skipped: owner decision. The owner kept it out of scope.
**Original issue:** `sized_risks_from_entry_intents` has no production caller.

### IN-01 .. IN-06: Info items
**Reason:** skipped: owner decision (out of scope for this run).

## Verification

**Where the checks ran:** all checks ran in the main checkout (`C:\Users\admin\Music\Trading`, branch
`develop`). `workflow.use_worktrees` is `false`, so no worktree was created. The results can be
reproduced from this tree.

| Check | Result |
|---|---|
| `uv run ruff check` | All checks passed |
| `uv run ruff format --check` | 664 files already formatted |
| `uv run mypy src` | Success: no issues found in 213 source files |
| Targeted pytest at HEAD 7c9f4b2b (18 files, listed below) | exit 0, 615 passed, 0 skipped |

The 18 files in the final pytest run, executed once with `TEST_DATABASE_URL` set, so the `_pg.py`
files actually ran:
- `tests/test_phase19_gate.py`
- `tests/test_execution_manager.py`
- `tests/test_demo_rehearsal_flow.py`
- `tests/test_demo_rehearsal_safety.py`
- `tests/test_pre_placement.py`
- `tests/test_protection_branches.py`
- `tests/test_protection_coordinator.py`
- `tests/test_protection_router_rig.py`
- `tests/test_protection_take_profits.py`
- `tests/test_emergency_market_close.py`
- `tests/test_execution_emergency.py`
- `tests/test_execution_attach.py`
- `tests/test_exchange_error_rejections.py`
- `tests/test_approval_replay_pg.py`
- `tests/test_execution_exactly_once_pg.py`
- `tests/test_execution_write_ahead_pg.py`
- `tests/test_intent_recovery_pg.py`
- `tests/test_realized_risk_persistence_pg.py`

During the work I also ran these:

- **Pre-fix code check, per finding:** I stashed only that finding's source files and kept the
  new tests. In each case the new regression tests FAILED: CR-01 (8 failures), CR-02 (11), CR-03
  (10) and WR-02 (4).
- **Extra suites:** these files also passed:
  - `tests/test_paper_shadow_isolation.py`
  - `tests/test_binance_usdm_signed_calls.py`
  - `tests/test_demo_probe_cases.py`
  - `tests/test_deploy_heartbeat.py`
  - `tests/test_paper_supervisor_backfill.py`

**Not run:**
- The full suite (`-m "not docker"`). The orchestrator runs it once per phase.
- The `-m docker` suite.
- `scripts/verify_decision_alignment.py`. No docs or AGENTS.md changed.
- The Demo rehearsal with `--execute`, or anything against the network.

---

_Fixed: 2026-10-20T10:05:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_

---

## Batch 1 (owner decisions WR-06 and WR-05)

**Fixed at:** 2026-10-20T10:20:00Z, on top of `1ec6ef0d` (branch `develop`). The CR-01, CR-02,
CR-03 and WR-02 commits above were kept as they are.
**Scope:** WR-06 and WR-05 only, as the owner decided them. Their "Skipped Issues" entries above
are superseded by this section. WR-01, WR-03, WR-04, WR-07 and IN-01..IN-06 stay skipped.

| Finding | Status | Commit |
|---|---|---|
| WR-06 | fixed for the MARK price; the LAST price is NOT done (recorded as open work) | `ddea17e4` |
| WR-05 | fixed: requires human verification (protection safety logic) | `2e5812e1` |

### WR-06: MARK_PRICE_OUTSIDE_ZONE refused the resting-limit case

**Status:** mark done, last price NOT done.
**Owner decision:** D-05 "left the entry zone" means the ADVERSE side only.
**Files modified:** `src/execution/pre_placement.py`, `tests/test_pre_placement.py`,
`tests/test_execution_manager.py`, `tests/test_demo_rehearsal_flow.py`,
`scripts/demo_rehearsal.py` (comments only), `docs/GLOSSARY.md` (the `MARK_PRICE_OUTSIDE_ZONE`
meaning), `19-OWNER-GAPS.md` (new row WR-06).
**Applied fix:**
- `check_mark_price` now refuses `MARK_PRICE_OUTSIDE_ZONE` only when a LONG mark is strictly
  below `entry_min_price`, or when a SHORT mark is strictly above `entry_max_price`. The exact
  edge passes.
- A LONG with the mark above the zone (or a SHORT below it) is allowed: the GTD LIMIT rests.
- The crossed-stop check, the age check and the fail-closed refusal on a missing or stale price
  are unchanged and still independent of the side rule.
- The Demo rehearsal zone (CR-02) is unchanged and still contains the mark. The adverse rule was
  not loosened for it.
- **Last price, not built.** The adapter has only `get_mark_price`. The open work item is
  written in the `check_mark_price` docstring, in the module docstring (Q2) and in the
  `19-OWNER-GAPS.md` row WR-06. It has three parts:
  1. a new adapter read;
  2. a last-price input to `check_mark_price` and `PrePlacementInputs`, with age and fail-closed
     rules;
  3. gate 5e wiring and tests.

**Existing tests changed, and why:**
- `tests/test_pre_placement.py::test_check_mark_price_position`:
  - These rows now expect a pass, because they are the favorable side: LONG `100.70`, SHORT
    `99.40`.
  - New rows:
    - LONG `150.00` and SHORT `50.00` (far on the favorable side)
    - LONG `99.49` and SHORT `100.61` (strictly past the adverse edge)
  - The edge rows (LONG `99.50`, SHORT `100.60`) are now commented as adverse boundaries that
    pass.
- `tests/test_execution_manager.py::_mark_cases`: the row "mark above the zone" (`102.01`,
  refused) was removed, because that is now the favorable side. A new row, "mark one tick below
  the zone" (`99.99`, refused), was added.
- `tests/test_demo_rehearsal_flow.py::test_a_mark_past_the_zone_cushion_is_still_refused`:
  - It moved the mark one tick ABOVE `entry_max`, which is now allowed. It now moves the mark one
    tick BELOW `entry_min`, which is the adverse side.
  - It is parametrized over `far` and `fill`.

**New regressions:**
- `test_wr06_only_the_adverse_side_refuses[LONG|SHORT]`
- `test_wr06_a_long_mark_at_the_edge_or_on_the_favorable_side_places[100.00|102.00|102.01|150.00]`
- `test_a_far_mark_above_the_zone_is_the_favorable_side_and_reaches_the_entry`

**Pre-fix check:** I restored only the HEAD `src/execution/pre_placement.py` and kept the new
tests. 9 tests failed: every favorable-side case.

The adverse-side and boundary cases PASS on the old code too. The old code already refused
outside both edges and let the edges pass, so those rows pin the behavior that was kept. They
do not detect the bug.

### WR-05: an ENTRY_STATE_UNKNOWN entry was never handed to the coordinator

**Status:** fixed: requires human verification (protection safety logic).
**Files modified:** `src/execution/manager.py`, `src/execution/protection.py`,
`src/execution/execution_limits.py`, `config/execution/execution-limits-v1.toml`,
`config/execution/README.md`, `docs/GLOSSARY.md` (`LIMITS_NOT_CONFIGURED`: "four" became
"five"), `scripts/demo_rehearsal.py` (comment and step text), `tests/support/execution_limits.py`,
`19-OWNER-GAPS.md`, `20-NOTES.md`, and the tests listed below.

**Manager:** the Q5 UNKNOWN path keeps everything it did before:
- SAFE_MODE `ENTRY_STATE_UNKNOWN`
- the intent recorded `UNKNOWN`, never rewritten to ACKED
- `RECONCILIATION_REQUIRED`
- exactly one `place_entry`

It then also calls `register_resting_entry(replace(resting_entry, entry_state_unknown=True))`.
This call uses the same try/except as the ACKED hand-off. A failed hand-off enters SAFE_MODE
`PROTECTION_HANDOFF_FAILED` and cancels the entry by its deterministic id. That is a cancel,
never a second entry.

`RestingEntry` gained two fields:
- `entry_state_unknown` (bool, default False)
- `entry_good_till_utc` (the `goodTillDate` actually sent; required when the flag is set)

The manager now computes `good_till_date_ms` once and uses it for both the order and the record.

**Coordinator:**
- It never sends an entry, and an answer that is not found=True keeps it waiting. The record is
  never removed.
- A found fill follows the normal fill -> stop -> cancel-remainder flow. The coordinator never
  leaves SAFE_MODE.
- If the entry has never been found by `entry_good_till_utc + protection.entry_unknown_grace_ms`
  (measured on the injected clock), the plan moves to a NEW protection state,
  `ENTRY_UNRESOLVED`:
  - it is not in `BLOCKING_STATES`, the same as AWAITING_FILL;
  - one `PROTECTION_ENTRY_UNRESOLVED` note is journaled;
  - from then on the entry is queried only every `UNRESOLVED_ENTRY_POLL_EVERY_N_STEPS` steps;
  - a stream fill is still acted on at once.
- When an unresolved entry is found:
  - filled: UNPROTECTED, then the stop;
  - ended without a fill: ENTRY_ENDED_NO_FILL;
  - still open: back to AWAITING_FILL and the every-step poll.
- An ACKED entry never becomes unresolved.

**New owner key:**
- `protection.entry_unknown_grace_ms = "NOT_CONFIGURED"`, in `[protection]` and in
  `[provenance.protection]`.
- It is loaded like the other keys. `require_live_ready()`, the manager gate and the
  coordinator constructor all refuse while it is unset.
- Tests use the fake value 9191 (`tests/support/execution_limits.py`). No real number was
  chosen and `docs/DECISIONS.md` was not edited.

**Choices for the owner to confirm:**
- **N = 10** (`UNRESOLVED_ENTRY_POLL_EVERY_N_STEPS`). The owner asked for a named module
  constant and gave no value, so I picked 10. It is a code cadence, not a safety limit, but the
  owner may want a different value.
- **`ENTRY_UNRESOLVED` is an eleventh `ProtectionState` name.** The owner asked for "an explicit
  unresolved state". Phase 20 reads these names, and the register now says "eleven".
- **On a failed UNKNOWN hand-off,** SAFE_MODE's current reason changes to
  `PROTECTION_HANDOFF_FAILED`, as on the ACKED path. `ENTRY_STATE_UNKNOWN` was entered first and
  is still recorded.
- **The grace is counted from the `goodTillDate`** the entry was sent with, which is the plan
  expiry floored to the second, read on the local injected clock. Any exchange clock drift must
  fit inside the owner's grace.

**Existing tests changed, and why:**
- These two tests pinned the old "nothing handed off" behavior with
  `registry.register_attempts == 0`. They now assert one hand-off with `entry_state_unknown is
  True`:
  - `tests/test_execution_manager.py::test_q5_place_entry_is_sent_once_for_every_error_kind`
    (UNKNOWN branch)
  - `::test_an_unknown_exchange_error_absent_by_the_probe_is_unknown_and_never_resent`
- These tests pin the limit key list. Each gained `entry_unknown_grace_ms` /
  `protection.entry_unknown_grace_ms`:
  - `tests/test_execution_manager.py::test_unset_limit_refuses_with_zero_adapter_calls`
  - `tests/test_protection_coordinator.py::test_constructor_refuses_while_any_limit_is_not_configured`
  - `tests/test_demo_rehearsal_flow.py::test_committed_not_configured_limits_abort_before_any_mutation`
- `tests/test_protection_coordinator.py`: `STATE_NAMES` gained `ENTRY_UNRESOLVED`. The test was
  renamed from `..._the_ten_stable_names` to `..._the_eleven_stable_names`.
- `tests/test_execution_limits.py`:
  - `EXPECTED_UNSET` gained the key.
  - The all-set document and the all-unset round trip assert the new field.
  - The committed-file `NOT_CONFIGURED` count went from 8 to 10.
  - `test_require_live_ready_refuses_naming_the_four_keys` was renamed to
    `test_require_live_ready_refuses_naming_every_key`. The `REQUIREMENT_TESTS` entry in
    `tests/test_phase19_gate.py` was updated to the new name.
- `tests/test_no_unratified_defaults.py`: `len(GUARDED_NAMES)` went from 34 to 35.

**New regressions:**
- `tests/test_execution_manager.py`:
  - `test_wr05_an_unknown_entry_is_registered_with_the_coordinator_and_sent_once`: the hand-off
    happens, `place_entry` is called exactly once, the intent is UNKNOWN, SAFE_MODE is kept, and
    the record carries the `goodTillDate` that was sent.
  - `test_wr05_the_acked_hand_off_carries_the_same_record_without_the_unknown_flag`
  - `test_wr05_a_failed_unknown_hand_off_is_fail_closed_like_the_acked_one`
  - `test_wr05_e2e_an_unknown_entry_that_exists_is_protected_by_the_real_coordinator`: the
    manager, the real coordinator and the stateful fake together. The entry is booked but its
    answer is lost and the probe fails. The UNKNOWN entry is registered, fills, gets the
    closePosition stop and the remainder cancel, and reaches PROTECTED. There is one
    `place_entry` and the intent stays UNKNOWN.
- `tests/test_protection_unknown_entry.py` (new, 11 tests):
  - record validation
  - the registration reason
  - stop after a fill, both REST and stream
  - found=False for 50 steps and then a day of steps: never forgotten and never re-sent, no
    stop intent, one note, SAFE_MODE kept
  - the exact GTD + grace boundary (1 ms short stays AWAITING_FILL) and the every-Nth-step query
    count over 3N steps
  - an unresolved entry found filled on the Nth step
  - a stream fill acted on at once
  - an entry found open goes back to the every-step poll
  - an entry found ended goes to ENTRY_ENDED_NO_FILL
  - an ACKED entry never becomes unresolved

**Pre-fix check:**
- With only the HEAD `src/execution/manager.py` restored, 17 manager tests failed: the four
  `wr05` tests, the 12 UNKNOWN cases of the Q5 matrix and the absent-probe test.
- With only the HEAD `src/execution/protection.py` restored, `tests/test_protection_unknown_entry.py`
  failed at collection.

### Batch 1 verification

**Where the checks ran:** all checks ran in the main checkout (`C:\Users\admin\Music\Trading`,
branch `develop`). `workflow.use_worktrees` is `false`, so no worktree was created.

| Check | Result |
|---|---|
| `uv run ruff check` | All checks passed |
| `uv run ruff format --check` | 665 files already formatted |
| `uv run mypy src` | Success: no issues found in 213 source files |
| `uv run python scripts/verify_decision_alignment.py all` | ALL_PASS |
| Targeted pytest, 18 files (listed below), with `TEST_DATABASE_URL` set, at the WR-05 tree | 683 passed, 0 skipped |

The 18 files in the targeted run:
- `tests/test_phase19_gate.py`
- `tests/test_execution_manager.py`
- `tests/test_pre_placement.py`
- `tests/test_demo_rehearsal_flow.py`
- `tests/test_demo_rehearsal_safety.py`
- `tests/test_protection_branches.py`
- `tests/test_protection_coordinator.py`
- `tests/test_protection_router_rig.py`
- `tests/test_protection_take_profits.py`
- `tests/test_protection_unknown_entry.py`
- `tests/test_execution_limits.py`
- `tests/test_no_unratified_defaults.py`
- `tests/test_emergency_market_close.py`
- `tests/test_execution_attach.py`
- `tests/test_execution_write_ahead_pg.py`
- `tests/test_execution_exactly_once_pg.py`
- `tests/test_approval_replay_pg.py`
- `tests/test_intent_recovery_pg.py`

The WR-06 commit was checked on its own before WR-05 began. These all passed on that tree:
- the 4 test files `tests/test_pre_placement.py`, `tests/test_execution_manager.py`,
  `tests/test_demo_rehearsal_flow.py` and `tests/test_phase19_gate.py`;
- ruff, the format check, mypy and the decision-alignment gate.

**Not run or not verified:**
- The full suite (`-m "not docker"`) and the `-m docker` suite.
- Any `--execute`, the Demo, or the network.
- The last-price check, which is not built.
- The low-frequency poll and the grace logic, beyond the fake exchange and virtual time. No real
  step loop exists yet (Phase 24).

_Batch 1 fixed: 2026-10-20T10:20:00Z_
_Fixer: Claude (gsd-code-fixer)_

---

## Batch 2 (owner decision WR-03)

**Fixed at:** 2026-10-20T10:40:00Z, on top of `2175754d` (branch `develop`). The CR-01, CR-02,
CR-03, WR-02, WR-06 and WR-05 commits above were kept as they are.
**Scope:** WR-03 only, as the owner decided it. Its "Skipped Issues" entry above is superseded by
this section. WR-01, WR-04, WR-07 and IN-01..IN-06 stay skipped.

| Finding | Status | Commit |
|---|---|---|
| WR-03 | fixed: requires human verification (emergency-close safety logic) | `0110b938` |

### WR-03: the emergency close could over-close

**Owner decision:** apply Q5 to the emergency close. Never send a second close order while the
result of the previous one is not determined, and do not rely on assumption A4.

**Files modified:**
- `src/execution/emergency_close.py`, `src/execution/execution_limits.py`
- `config/execution/execution-limits-v1.toml`, `config/execution/README.md`
- `docs/GLOSSARY.md`: the `LIMITS_NOT_CONFIGURED` row, "five" became "six"
- `scripts/demo_rehearsal.py`: passes `limits=` to the closer, plus a comment count
- `tests/support/execution_limits.py`, `tests/support/fake_binance_exchange.py`,
  `tests/support/protection_doubles.py`
- `19-OWNER-GAPS.md`: hard-limits line, O-04, a new WR-03 row, the A4 row, and section 4
- `20-NOTES.md`: one bullet on the restart gap
- the tests listed below

`src/execution/protection.py` was not changed. The coordinator already calls the closer on every
CLOSE_REQUIRED / CLOSE_FAILED step, and that call is now the poll.

**Applied fix (closer):**
- **An ACK is PENDING, never CLOSED.** `place_market_close` returning is journaled
  `post_send` (the ACK), and the attempt is then queried by its deterministic id. Only a query
  answering FILLED (journaled `filled`) or another terminal status (CANCELED, EXPIRED,
  EXPIRED_IN_MATCH, REJECTED, journaled `ended_unfilled`) ends the attempt.
- **One pending attempt per plan, in process.** `_PendingAttempt` holds the attempt number, id,
  send time, `seen` (an ACK or a find proved it exists), a sticky `unknown_code` and the
  `alerted` flag. It is written BEFORE the send and dropped only when nothing was placed
  (PreSendRefusal, definitive rejection) or a query proves it terminal.
- **Every call queries the pending attempt first.** While it is not terminal the call sends
  nothing and answers False, with one of two statuses:
  - `PENDING` (new `EmergencyCloseStatus` member, reason `ATTEMPT_NOT_TERMINAL`), or
  - `PENDING_UNKNOWN`.
- **found=False is never absence for a sent attempt.**
  - Right after an ambiguous send it gives `ABSENT_AFTER_AMBIGUOUS_SEND`.
  - After an ACK or an earlier find it gives `ATTEMPT_NOT_FOUND_AFTER_ACK`.
  - Both are UNKNOWN and no new attempt is created.
  - A failed or indeterminate query of an attempt never seen is UNKNOWN (`PROBE_FAILED`,
    `PROBE_INDETERMINATE`). Of an attempt known to exist, it only waits.
  - A found status that is neither NEW/PARTIALLY_FILLED nor terminal is UNKNOWN
    (`ATTEMPT_STATUS_UNREADABLE`).
- **`discover_next_attempt_no`** now raises `CloseAttemptNotTerminal` (a `ValueError`) for a found
  attempt whose status is not terminal. `found=False` for a number never sent keeps its meaning:
  that number is free. The closer adopts the named attempt as pending (`ATTEMPT_HISTORY_NOT_TERMINAL`,
  UNKNOWN) and sends nothing.
- **After the attempt is terminal:** the position is re-read, with the CR-03 rule of two
  consecutive zero reads unchanged. Exposure that remains gets the next attempt under a NEW id
  (discovery as before), sized from that REST read and split by MARKET_LOT_SIZE as before.
- **Poll deadline:** `elapsed_ms = (clock() - sent_at) // 1 ms`, injected clock, whole
  milliseconds. When it is `>= protection.emergency_close_poll_timeout_ms` and the attempt is
  still not terminal, the attempt becomes UNKNOWN (`CLOSE_POLL_DEADLINE_PASSED`).
- **One alert per episode.** The first time a pending attempt is UNKNOWN, for any reason
  including the deadline: SAFE_MODE `EMERGENCY_CLOSE_FAILED`, ONE critical alert
  `EMERGENCY_CLOSE_FAILED` and one `failed` journal row. Every later call reports
  `PENDING_UNKNOWN` without another alert. The attempt keeps being queried, and no overlapping
  close is ever sent.
- **New owner key:** `protection.emergency_close_poll_timeout_ms = "NOT_CONFIGURED"`, in
  `[protection]` and in `[provenance.protection]`. It is loaded like `entry_unknown_grace_ms`.
  `MarketEmergencyCloser` now takes a required `limits=` argument and refuses at construction,
  like the coordinator: it calls `limits.require_live_ready()`, then raises
  `ExecutionLimitsNotConfigured` naming the key if the key is unset. The closer never reads
  `max_unprotected_ms`. Tests use the fake value 6161; no real number was chosen and
  `docs/DECISIONS.md` was not edited.
- **Kept:** deterministic ids, query before any resend, MARKET_LOT_SIZE parts, the per-call
  parts bound (now counted on confirmed parts), the CR-03 rule, the Hedge refusal, and the
  NOT_SENT and REJECTED paths.

**Choices for the owner to confirm:**
1. **The alert episode is the pending attempt.** An attempt that becomes UNKNOWN for a reason
   other than the deadline (ambiguous send then found=False, a failed first probe, an unreadable
   status, an adopted history attempt) alerts at once, as before the fix. It does not alert
   again at the deadline. So there is at most one alert per attempt, and possibly an earlier
   one than the deadline.
2. **A found NEW/PARTIALLY_FILLED attempt after an ambiguous send is now `PENDING`** (no SAFE_MODE
   from the closer, no alert) until the deadline. Before the fix it was `PENDING_UNKNOWN` with an
   immediate alert. The coordinator's own SAFE_MODE `CLOSE_REQUIRED` and alert are already in
   force at that point.
3. **found=False after an ACK is UNKNOWN** (`ATTEMPT_NOT_FOUND_AFTER_ACK`). The owner's text
   covered found=False after an ambiguous send. I applied the same rule here because the ACK
   proved the order existed.
4. **An attempt adopted from the exchange history** (found and not terminal at discovery, for
   example after a restart) has its deadline counted from the moment it was adopted, because the
   real send time is unknown. It alerts at once because its origin is unknown.
5. **The closer constructor calls `require_live_ready()`,** so it refuses while ANY execution
   limit is unset, the same as the coordinator. It does not refuse only on its own key.
6. **The coordinator's journal reason stays `CLOSE_FAILED`** while a close is merely pending. The
   state is CLOSE_FAILED (blocking, retried every step), which is correct, but the reason text
   does not say "pending". I did not add a new reason to `protection.py`.
7. **The pending attempt is in-process only.** After a restart, an ambiguous attempt the exchange
   does not show (found=False) is forgotten. `discover_next_attempt_no` would then hand out the
   same number again and the close would be re-sent under that id. This restart gap is recorded
   in `19-OWNER-GAPS.md` (rows WR-03 and A4) and in `20-NOTES.md`. It belongs with the
   coordinator rebuild (Phase 20/24, G4-029).

**Existing tests changed, and why:**
- `tests/test_emergency_market_close.py`:
  - `make_close_rig` and the "restart" closer in
    `test_a_second_call_after_a_crash_never_reuses_an_attempt_id` pass
    `limits=limits_with()`. The helper is imported under an alias so pytest does not collect it.
  - `test_tracer_journals_pre_send_before_the_send_and_post_send_after`: the expected journal
    order gains `journal:filled`, the query that proves the fill.
  - `test_a_call_never_sends_more_parts_than_the_first_position_needs`: the ACK-only stub was
    counted as three closed parts. Each part now has to be reported FILLED by a query stub
    before it counts. The position stub stays stuck, so the parts bound (3 sends,
    `PARTS_EXHAUSTED`) is still what the test proves.
  - `test_a_found_but_non_terminal_or_unknown_attempt_stops_without_a_resend[NEW|PARTIALLY_FILLED|SOMETHING_ELSE|None]`
    was split in two:
    - `test_a_found_active_attempt_after_an_ambiguous_send_is_pending_without_a_resend[NEW|PARTIALLY_FILLED]`
      now expects `PENDING`, no SAFE_MODE and no alert (choice 2).
    - `test_a_found_attempt_with_an_unreadable_status_stops_without_a_resend[SOMETHING_ELSE|None]`
      keeps the old expectation.
  - `test_definitive_absence_sends_the_next_part_under_a_new_attempt_id` and
    `test_repeated_definitive_absence_is_bounded_by_the_planned_parts` encoded the bug: found=False
    after an ambiguous send led to a new send. Both were replaced by
    `test_wr03_absence_right_after_an_ambiguous_send_is_unknown_and_never_resent`.
  - `script_probes` now falls back to the fake's real query once its script is exhausted, because
    every sent attempt is now queried. This keeps
    `test_an_attempt_found_terminal_without_closing_gets_a_fresh_id_for_the_next_part`
    unchanged.
- Key-set pins gained `emergency_close_poll_timeout_ms` /
  `protection.emergency_close_poll_timeout_ms`:
  - `tests/test_execution_limits.py`: `EXPECTED_UNSET`, the all-set document (value 13), the
    all-unset round trip, the module docstring, and the committed-file `NOT_CONFIGURED` count,
    which went from 10 to 12.
  - `tests/test_no_unratified_defaults.py`: `len(GUARDED_NAMES)` went from 35 to 36.
  - `tests/test_execution_manager.py::test_unset_limit_refuses_with_zero_adapter_calls`
  - `tests/test_protection_coordinator.py::test_constructor_refuses_while_any_limit_is_not_configured`
  - `tests/test_demo_rehearsal_flow.py::test_committed_not_configured_limits_abort_before_any_mutation`
  - `tests/test_phase19_gate.py` needed no edit. Its execution-limits invariant iterates
    `EXECUTION_LIMIT_KEYS`.
- Test support:
  - `tests/support/execution_limits.py` gained the fake value 6161.
  - `tests/support/protection_doubles.py::make_rig` passes the same limits to the real closer.
  - `tests/support/fake_binance_exchange.py` gained the opt-in flag `market_close_rests`: a close
    is booked OPEN as NEW, nothing is executed, and the test fills or cancels it. The default
    behavior is unchanged.

**New regressions** (all in `tests/test_emergency_market_close.py`):
- `test_wr03_an_ack_new_with_nothing_executed_is_pending_and_nothing_else_is_sent`
- `test_wr03_polled_to_filled_then_two_flat_reads_is_closed`
- `test_wr03_polled_to_filled_with_exposure_left_sends_a_new_id_sized_from_rest`: a late entry
  fill while 0001 rests. 0002 is sent for the reconciled 0.003.
- `test_wr03_an_attempt_ended_unfilled_while_pending_gets_a_new_id`
- `test_wr03_absence_right_after_an_ambiguous_send_is_unknown_and_never_resent`: 6 calls, one send,
  one alert.
- `test_wr03_discovery_stops_on_a_found_attempt_that_is_not_terminal`: direct discovery, plus a
  fresh closer that adopts the attempt, sends nothing, alerts once, and closes after the fill.
- `test_wr03_the_poll_deadline_holds_unknown_with_one_alert_and_no_second_send`: 6160 ms is
  PENDING, 6161 ms is UNKNOWN. Ten more calls 60 s apart give one alert and one send, with
  SAFE_MODE kept.
- `test_wr03_the_deadline_is_the_new_limit_never_max_unprotected_ms[50000-1-50000|1000-1000000000-1000]`
- `test_wr03_the_closer_never_reads_max_unprotected_ms` (AST)
- `test_wr03_the_closer_refuses_while_its_poll_deadline_is_not_configured`
- `test_wr03_found_false_after_an_ack_is_unknown_and_never_resent`
- `test_wr03_coordinator_keeps_a_resting_close_blocking_and_never_sends_a_second`: the real
  coordinator with B5. CLOSE_FAILED stays blocking for 5 steps with one close, then FLAT after
  the fill.

**Pre-fix check:**
- I restored the HEAD `src/execution/emergency_close.py`, with only a `limits: Any = None`
  argument added so that construction works, and kept the new tests. Result: 16 failed and
  1 error.
- The failures are every new `wr03` test, the two `PENDING` cases and the tracer journal order.
- The error comes from `test_wr03_found_false_after_an_ack_is_unknown_and_never_resent`. Under
  the old code the file's autouse guard caught attempt id 0001 being SENT TWICE.
- The key-set pins fail on the old loader by construction, because the key did not exist.

### Batch 2 verification

**Where the checks ran:** all checks ran in the main checkout (`C:\Users\admin\Music\Trading`,
branch `develop`). `workflow.use_worktrees` is `false`, so no worktree was created.

| Check | Result |
|---|---|
| `uv run ruff check` | All checks passed |
| `uv run ruff format --check` | 665 files already formatted |
| `uv run mypy src` | Success: no issues found in 213 source files |
| `uv run python scripts/verify_decision_alignment.py all` | ALL_PASS |
| Targeted pytest, 17 files (listed below) | 624 passed, 0 skipped |

The 17 files in the targeted run:
- `tests/test_emergency_market_close.py`
- `tests/test_protection_branches.py`
- `tests/test_protection_coordinator.py`
- `tests/test_protection_router_rig.py`
- `tests/test_protection_take_profits.py`
- `tests/test_protection_unknown_entry.py`
- `tests/test_phase19_gate.py`
- `tests/test_execution_limits.py`
- `tests/test_no_unratified_defaults.py`
- `tests/test_execution_manager.py`
- `tests/test_demo_rehearsal_flow.py`
- `tests/test_exchange_error_rejections.py`
- `tests/test_demo_rehearsal_safety.py`
- `tests/test_execution_emergency.py`
- `tests/test_fake_exchange_v2.py`
- `tests/test_paper_shadow_isolation.py`
- `tests/test_binance_usdm_source_guard.py`

The last six are consumers of the changed fake and closer. None is a `_pg.py` file, so
`TEST_DATABASE_URL` was not needed.

**Not run or not verified:**
- The full suite (`-m "not docker"`) and the `-m docker` suite.
- Any `--execute`, the Demo, or the network.
- Real Binance behavior of a reduce-only MARKET close. Whether an ACK is NEW, how long until
  FILLED, and the -2022/-2024 answers are still probe P9 (A4/A8).
- The restart gap of choice 7.
- The coordinator cadence that drives the polling is still Phase 24. Without a step loop, a
  pending close is not polled in a real process.

_Batch 2 fixed: 2026-10-20T10:40:00Z_
_Fixer: Claude (gsd-code-fixer)_

---

## Batch 3 (owner decision WR-04, DECISIONS D077)

**Fixed at:** 2026-10-20T11:10:00Z, on top of `c7254259` (branch `develop`). The CR-01, CR-02,
CR-03, WR-02, WR-06, WR-05 and WR-03 commits above were kept as they are.
**Scope:** WR-04 and the DECISIONS row that records its policy, as the owner decided them. The
"Skipped Issues" entry for WR-04 above is superseded by this section. WR-01, WR-07 and
IN-01..IN-06 stay skipped.

| Finding / item | Status | Commit |
|---|---|---|
| WR-04 | fixed: requires human verification (protection safety logic) | `06445e6f` |
| D077 row and renumbering of the provisional D-10 / Q5 ids | done | `e4b10e09` |

### WR-04: a once-confirmed stop that is lost left the plan non-blocking and unescalated

**Owner decision:** for a stop that REST confirmed ACTIVE and that later reads ABSENT or
NOT_ACTIVE, the stop is never re-placed. Confirmed exposure is CLOSE_REQUIRED with a MARKET close
(P6/B4). An unreadable position, or a zero position while the entry is not terminal, is
UNPROTECTED (blocking) with `stop_lost_at` recorded once. `max_unprotected_ms` from
`stop_lost_at` without a safe state (position zero AND entry terminal) escalates to
CLOSE_REQUIRED. No MARKET close is ever sent with a guessed quantity.

**Files modified:**
- `src/execution/protection.py`
- `tests/test_protection_branches.py`
- `tests/test_protection_stop_lost.py` (new)
- `19-OWNER-GAPS.md`: a new WR-04 row and the status sentence
- `20-NOTES.md`: one bullet on the restart gap and the criterion 2 wording

**Applied fix (coordinator):**
- `_Tracked.stop_lost_at` is set once, at the first detection, and never reset. It is exposed as
  `PlanProtection.stop_lost_at_utc`, a new field with default `None`.
  `stop_confirmed_at_utc` keeps the earlier confirmation.
- `_confirm` was restructured:
  - A stop is lost when it was seen lost before, or when a stop confirmed on an earlier step reads
    ABSENT or NOT_ACTIVE now.
  - A lost stop is never queried again and never re-placed. The "absent, place the same id again"
    branch now runs only for a stop that was never confirmed.
  - One unprotected-deadline branch covers both a stop that was never confirmed (B2/B3, unchanged)
    and a lost stop. `_unprotected_deadline_reached` measures from `stop_lost_at` when it is set,
    otherwise from the first fill, using the same helper. `_elapsed_ms` now takes the start time.
  - The new branch code `B4_STOP_LOST_UNRESOLVED` is chosen by `_unprotected_branch`.
  - A lost stop never reaches `_settle_state`. `_settle_state` also refuses a plan with
    `stop_lost_at` set, as a second guard.
- `_on_stop_lost` now runs on the detection step and on every later step. It decides as follows:
  - exposure: B4 (`B4_FILL_AFTER_STOP`, unchanged);
  - flat with a terminal entry and a confirming second zero read (CR-03): FLAT
    (`STOP_CONSUMED_FLAT`, unchanged);
  - anything else: a transition to UNPROTECTED with the new reason `STOP_LOST`, once.
- On the deadline, `_enter_close_required` runs as before: SAFE_MODE `CLOSE_REQUIRED`, one
  `CLOSE_REQUIRED` alert per plan (the state is entered once), then the closer. The closer reads
  the position itself. If it cannot read it, it fails closed without sending (`POSITION_READ_FAILED`)
  and the plan is CLOSE_FAILED, which keeps blocking and retries every step.
- **Unchanged:**
  - the B1, B2, B3, B5 and -4509 branches;
  - B4 with confirmed exposure, which is still immediate;
  - the CR-03 two-read rule;
  - the closer;
  - every limit key. `max_unprotected_ms` stays `NOT_CONFIGURED`; the tests use the TEST_ONLY 7777
    on virtual time.

**The CR-03 interaction (the note under CR-03 above):**
- **Old behavior:** in the stop-lost gap case with a terminal entry, the plan stayed
  PROTECTED_ENTRY_OPEN. The next step did not read the stop (the entry was terminal and the stop
  had been confirmed once), so `_settle_state` moved the plan to PROTECTED. The step after that
  attached TP1/TP2 while the stop was not active.
- **The fix covers it two ways:**
  1. The gap case now moves to UNPROTECTED (blocking) and never returns to `_settle_state`.
  2. `_settle_state` itself refuses any plan with `stop_lost_at`.
- **What happens now:** each following step reads the position. Confirmed exposure is B4. Two
  zero reads with a terminal entry are FLAT. Nothing else leaves UNPROTECTED before the deadline.
- **Tests:** `test_branch_stop_lost_one_empty_position_read_never_sweeps_an_open_position` and
  `test_wr04_stop_lost_entry_terminal_unreadable_then_exposed_is_b4_not_protected` assert that
  PROTECTED / COMPLETE never appear and that `place_algo_protective` is called once in total (no
  TP, no second stop).

**Choices for the owner to confirm:**
1. **A lost stop is never trusted again,** even if a later read would show ACTIVE. The coordinator
   stops querying it after the loss. The only exits from the stop-lost UNPROTECTED are B4,
   FLAT (position zero AND entry terminal, two reads) or the deadline. The owner's text names
   only those exits.
2. **No SAFE_MODE and no alert when the plan enters the stop-lost UNPROTECTED.** It only blocks
   through `blocks_new_entries()`, the same as an UNPROTECTED plan after a first fill. SAFE_MODE
   and the one CLOSE_REQUIRED alert come at the escalation (or at once on B4). The owner's text
   asked for the blocking state, not for an alert at entry.
3. **The deadline branch code is the new `B4_STOP_LOST_UNRESOLVED`.** It is not B2 or B3, so the
   journal shows why the plan was closed. Exposure found later in this state keeps the existing
   B4 code `B4_FILL_AFTER_STOP`.
4. **A zero read that the second read contradicts (a non-zero second read) is treated as "not
   proven".** The plan stays in UNPROTECTED and the next step reads again, which gives B4 if the
   exposure is still there. The alternative was immediate B4 on the second read. I kept the
   CR-03 gap handling.
5. **B1 (entry_terminal_timeout_ms) does not apply once the stop is lost.** The lost-stop deadline
   from `stop_lost_at` governs. B1 still applies, unchanged, while the stop is confirmed.
6. **Alert flood (IN-01, still open):** the coordinator's `CLOSE_REQUIRED` alert is sent once, but
   while the position stays unreadable the closer's own `EMERGENCY_CLOSE_FAILED` /
   `POSITION_READ_FAILED` alert repeats on every CLOSE_FAILED step. The owner said to let the
   closer's existing rules decide, so the closer was not changed. The "alert once" part of the
   decision therefore holds for the coordinator alert only.
7. **`stop_lost_at` is in-process,** like the rest of the coordinator state. A restart loses it.
   The rebuild belongs to Phase 20/24 (G4-029) and is noted in `20-NOTES.md`.

**Existing tests changed, and why:**
- `tests/test_protection_branches.py::test_branch_stop_consumed_with_a_flat_position_and_terminal_entry_ends_flat`:
  - Old assertion: after the stop triggered with the entry still open, the plan was
    PROTECTED_ENTRY_OPEN (non-blocking). That pinned exactly the WR-04 gap.
  - New assertion: UNPROTECTED with reason `STOP_LOST` and `blocks_new_entries()` True.
  - The rest is unchanged: FLAT on the next step, no close, no alert, one placement.
- `tests/test_protection_branches.py::test_branch_stop_lost_one_empty_position_read_never_sweeps_the_legs`
  was renamed to `..._never_sweeps_an_open_position`:
  - It kept the CR-03 assertions: one empty read is not FLAT, there is no sweep, and one gap note
    is journaled.
  - It used to assert that FLAT never happens over three more steps. Under the old code that held
    because the plan settled to PROTECTED and attached TPs (the CR-03 interaction).
  - It now asserts UNPROTECTED (blocking), then B4 on the next real read, one MARKET close of
    0.004, FLAT, and the sweep only after the close. It also asserts that PROTECTED / COMPLETE
    never appear and there is no second placement.
  - Its docstring said WR-04 was not changed. The docstring now describes the owner decision.
- `test_branch_stop_consumed_flat_reads_the_position_twice_before_flat` was not edited. It still
  passes, with exactly two position reads on the FLAT step.
- No other test file changed. `tests/test_phase19_gate.py` pins no stop-lost test name or branch
  code.

**New regressions** (`tests/test_protection_stop_lost.py`, 7 tests):
- `test_wr04_stop_lost_position_unreadable_throughout_escalates_from_stop_lost_at`:
  - PROTECTED_ENTRY_OPEN -> UNPROTECTED -> CLOSE_REQUIRED (-> CLOSE_FAILED), with every position
    read failing.
  - The loss is detected 1000 ms after the first fill. It is still UNPROTECTED at
    `stop_lost_at + 7776` ms and CLOSE_REQUIRED (`B4_STOP_LOST_UNRESOLVED`) at `+7777` ms.
  - `stop_lost_at_utc` never changes across the failed polls.
  - The stop is queried once after the loss and never again.
  - No `place_market_close`, one CLOSE_REQUIRED alert, still blocking three steps later, and one
    placement in total.
- `test_wr04_stop_lost_position_zero_entry_open_is_not_safe_and_escalates`:
  - PROTECTED_ENTRY_OPEN -> UNPROTECTED -> CLOSE_REQUIRED, with the position flat and the entry
    open.
  - At the deadline: SAFE_MODE `CLOSE_REQUIRED` and one alert. Nothing is sent, because two reads
    are flat. The plan stays CLOSE_REQUIRED and blocking while the entry is open, and is FLAT
    once the entry ends.
- `test_wr04_stop_lost_with_exposure_closes_at_once_and_never_places_a_stop`: immediate B4, one
  MARKET close of 0.004, `stop_lost_at_utc` set, no placement call after the loss, and FLAT.
- `test_wr04_a_canceled_or_missing_stop_is_never_replaced[canceled|missing]`:
  - CANCELED (NOT_ACTIVE) and absent (ABSENT, the reading that re-places a stop that was never
    confirmed).
  - Three unreadable steps stay UNPROTECTED with no placement, then B4 once the position is read.
  - This is the D034 "missing or canceled SL" case that D077 overrides.
- `test_wr04_stop_lost_entry_terminal_unreadable_then_exposed_is_b4_not_protected`: the CR-03
  interaction (see above).
- `test_wr04_stop_lost_settles_flat_only_after_two_consecutive_zero_reads`:
  - An unreadable read is UNPROTECTED.
  - One zero read followed by a failed confirming read is still UNPROTECTED, with no sweep.
  - Two zero reads give FLAT (`STOP_CONSUMED_FLAT`) with exactly two `snapshot_positions` calls
    on that step.
  - PROTECTED never appears.

**Pre-fix check:**
- I restored only the HEAD `src/execution/protection.py` and kept the new and changed tests.
- Every new test failed: all 7 in `test_protection_stop_lost.py`, both parameter cases included.
  Both changed tests in `test_protection_branches.py` failed too.
- Honest note on `test_wr04_stop_lost_with_exposure_closes_at_once_and_never_places_a_stop`: the
  immediate B4 itself already existed. This test fails on the old code only through its
  `stop_lost_at_utc` assertion (`AttributeError`), not through the close behavior. The other six
  fail on a behavior assertion: the old code kept PROTECTED_ENTRY_OPEN.

### D077 and the provisional ids

- **`docs/DECISIONS.md`:** one new row, D077, in the file's existing style.
  - Status: "Accepted (2026-10-20, owner decision typed in the Phase 19 review session)".
  - The text states the stop-lost policy and the scope (this branch only).
  - It overrides D034's automatic re-placement of a missing or canceled SL for this branch only.
    D034 stays for a failed initial placement and for "SAFE_MODE blocks new ENTRIES only".
  - It says P6 (Demo, assumption A3) is NOT observed, so the policy is a design choice, not a
    measurement.
  - It says `max_unprotected_ms` stays `NOT_CONFIGURED`.
  - D034's own row text is byte-unchanged.
- **Gates:** `verify_decision_alignment.py all` is ALL_PASS. DC-02 (contiguous D001..D077), DC-01
  and the AU/PR checks need only the row. No gate requires a `docs/DOC_STATUS.md` line for a new
  row: DC-05 checks only the 2026-09-30 D044 line, and PR-01 only protocol rows. So DOC_STATUS was
  not edited. The row carries no "protocol vX frozen" text and not the Phase 18 title, so
  `research-gate.yml` and `_phase18_row()` are unaffected.
- **Renumbered provisional ids:** D-10 (the D055 closure) moved from D077 to **D078**, and Q5 from
  D078 to **D079**. Changed files:
  - `19-DEC-D055-DRAFT.md` and `19-DEC-Q5-DRAFT.md` (the status lines now say "`docs/DECISIONS.md`
    has no row for it" instead of "was not edited")
  - `19-OWNER-GAPS.md`: the hard-limits line now records the D077 edit, plus O-01, Q5 and
    section 5
  - `19-NOTES.md`, `19-17-SUMMARY.md`
  - `.planning/STATE.md`, `.planning/codebase/CONCERNS.md`
  - `.planning/quick/261020-jua-.../261020-jua-SUMMARY.md`

  **Both rows remain drafts and are NOT written.** D055 stays OPEN.
- **Left as they are on purpose:** the "D077" mentions in the Phase 18 files (`18-26-PLAN.md`,
  `18-26-SUMMARY.md`, `18-DEC-TAXONOMY-CODES.md`) and in `261020-jua-PLAN.md`. They record the
  "next free number" at the time they were written, are not D-10/Q5 provisional ids, and are
  historical records. `19-CONTEXT.md` and the 2x-NOTES files carried no provisional id.
  `tests/test_phase19_gate.py` pins no id text.

### Batch 3 verification

**Where the checks ran:** all checks ran in the main checkout (`C:\Users\admin\Music\Trading`,
branch `develop`). `workflow.use_worktrees` is `false`, so no worktree was created.

| Check | Result |
|---|---|
| `uv run ruff check` | All checks passed |
| `uv run ruff format --check` | 666 files already formatted |
| `uv run mypy src` | Success: no issues found in 213 source files |
| `uv run python scripts/verify_decision_alignment.py all` | ALL_PASS |
| Targeted pytest at `e4b10e09`, 11 files plus the `test_decision_alignment*.py` glob (listed below) | 771 passed, 0 skipped |

The files in the targeted run:
- `tests/test_protection_branches.py`
- `tests/test_protection_coordinator.py`
- `tests/test_protection_router_rig.py`
- `tests/test_protection_take_profits.py`
- `tests/test_protection_unknown_entry.py`
- `tests/test_protection_stop_lost.py`
- `tests/test_emergency_market_close.py`
- `tests/test_phase19_gate.py`
- `tests/test_execution_manager.py`
- `tests/test_decision_alignment*.py`
- `tests/test_demo_rehearsal_flow.py`

**Also run, because they read `docs/DECISIONS.md`:**
- `tests/test_phase18_gate.py`, `tests/test_binance_limits_ratified_file.py`,
  `tests/test_research_protocol_v250.py`, `tests/test_research_protocol_v260.py`,
  `tests/test_research_gate_negative.py`, `tests/test_kill_gate_docs.py` and
  `tests/test_deploy_docs.py`.
- Result: 559 passed, 1 failed.
- **Pre-existing failure, not caused by this batch:**
  `tests/test_phase18_gate.py::test_invariant_5_no_unratified_default_in_src_or_scripts` asserts
  `len(GUARDED_NAMES) == 34`. Batches 1 and 2 raised it to 36 in
  `tests/test_no_unratified_defaults.py` (`2e5812e1`, `0110b938`) and did not run this gate. This
  batch changed neither file, and the failure is independent of DECISIONS.md. It is not fixed
  here; it needs the pin moved to 36 with a comment, in a separate change.

**Not run or not verified:**
- The full suite (`-m "not docker"`) and the `-m docker` suite.
- Any `--execute`, the Demo, or the network.
- P6 / A3: whether Binance cancels a closePosition stop with its position, and what a lost stop
  reads as (ABSENT or which NOT_ACTIVE status). D077 is a design choice.
- A real step cadence: the coordinator is still stepped only by tests and the rehearsal
  (Phase 24).
- The restart rebuild of `stop_lost_at` (choice 7).

_Batch 3 fixed: 2026-10-20T11:10:00Z_
_Fixer: Claude (gsd-code-fixer)_
