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
