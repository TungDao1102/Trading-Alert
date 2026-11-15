---
phase: 20-reconcile-safe-mode-hardening
plan: 27
subsystem: execution
tags: [gap-closure, review-fix, intent-recovery, emergency-close, protection, taxonomy]
gap_closure: true
requirements-addressed: []
status: complete
commits: 7
plan_head_before: ffe13a74
plan_head_after: a8a49d4f45b73790c10f2531e551af9b56aae97d
key-files:
  created:
    - tests/test_emergency_close_gate_refusal.py
    - tests/test_protection_demo_shapes.py
  modified:
    - src/execution/intent_recovery.py
    - src/execution/emergency_close.py
    - src/execution/manager.py
    - src/execution/protection.py
    - src/domain/exchange_errors.py
    - tests/test_intent_recovery_unknown_entry.py
    - tests/test_manual_controls.py
    - tests/test_drills.py
    - tests/fixtures/phase8/drill_log/expected.json
    - tests/test_protection_branches.py
    - tests/test_exchange_errors.py
---

# Phase 20 Plan 27: Review fixes WR-A1 to WR-A3, listing-based stop confirmation, -5040 Summary

Five owner-approved fixes (2026-10-23): an UNKNOWN entry can close after a failed finalize write, a REST-gate refusal at any closer read is a NOT_SENT close, the manual close removes the legs of a filled flat plan, a never-confirmed stop is confirmed by the open-algo-orders listing when the by-id query lags (Binance Demo shapes), and `-5040` joins the taxonomy. Evidence is executed tests with fakes only; nothing is [DEMO] except the observations quoted from the 2026-10-22 Demo evidence file. No requirement is marked complete. D055 stays as the owner left it; live placement stays disabled.

## What changed

1. **WR-A1 (`intent_recovery.py`).** Verified against the source: `exit_evidence_event` keys the row on (correlation, type, entity, transition) and puts `observed_at_utc` in `payload_json`, which `PgJournalStore` compares as identity. A retry after a failed finalize or ack write rebuilt the same id with a new time, so `JournalConflict` made every later step `KEPT_JOURNAL_FAILED`. Fix: `_exit_event` replaces the id of the event with `content_hash_event_id(EXIT_EVIDENCE_PREFIX, ...)` over the observation (event type, entity, time, payload). The evidence content is unchanged. Each observation is its own append-only row; the same observation replayed is still one row. `stream_records.py` and `entities.py` were not touched (the persistence entity writers write the evidence row in the same transaction as the status update, so they have no partial state to retry).
2. **WR-A2 (`emergency_close.py`).** Verified: `_read_position` is the first gated call and the generic `except Exception` made it `POSITION_READ_FAILED`. `PreSendRefusal` (decided by exception TYPE; only `reason` and `retry_after_seconds` attributes are read, never message text) now goes to `_not_sent` ahead of the generic handler at five sites: the first position read, the lot-filter read (direct and through `LotFilterSource`), the attempt discovery, the position re-read after a part, and the second flat-confirmation read. The result is the durable `CLOSE_NOT_SENT` row, status `NOT_SENT`, the not-sent alert, and no SAFE_MODE from the refusal. `_send_part` shares the new `_refusal_outcome` helper.
3. **WR-A3 (`manager.py`).** Verified: a filled entry gave `FILLED_OR_PARTIAL`, hence `KEEP_ENTRY_NOT_TERMINAL`, so the "second call once flat" never removed legs. `_protectives_keep_reason` now takes the entry client id; after two fresh zero reads, a `FILLED_OR_PARTIAL` verdict is followed by one more `confirm_entry_cancel` with a `CancelDetail`: exact `FILLED` (or an entry that is gone by now) lets the legs go; `PARTIALLY_FILLED` keeps them with the new code `ENTRY_PARTIALLY_FILLED`; an unreadable follow-up keeps them with `ENTRY_NOT_TERMINAL`. `CancelVerdict` is unchanged (no new enum member, no pin touched). The docstrings are corrected.
4. **Stop confirmation (`protection.py`).** `_cross_check_stop` runs after every by-id stop query in `_confirm`, `_supervise_stop` and the operator-protect read. For found=False of a stop REST never showed by id it reads `snapshot_open_algo_orders(symbol)` in the same step: listed means found=True with the listed status (ACTIVE class is REST-confirmed through the same bookkeeping as a found=True answer; a non-ACTIVE status is NOT_ACTIVE), read and not listed means the by-id answer stands (ABSENT, the unchanged B2/B3 same-id re-place, at most once per step, plan price), an unreadable listing or one that is not a list is UNREADABLE (journaled with the call name `snapshot_open_algo_orders`, never re-places). `-4116` (`DUPLICATE_CLIENT_ID`) on a placement is the new outcome `DUPLICATE`: journaled `PROTECTION_STOP_EXISTS_AWAITING_REST`, flag `stop_exists_unconfirmed`, not B5, not protection; the flag ends when a later by-id or listing read shows the id, or when both reads of a later step deny it (then the one same-step re-place is allowed). The user-data stream is not read. `ProtectionAdapter` gained `snapshot_open_algo_orders`. The module docstring carries the B2/B3 table; `tests/test_protection_branches.py` carries the test table.
5. **`-5040` (`exchange_errors.py`).** Row added after `-4509`: `REJECTED_DEFINITIVE` on PLACEMENT only, evidence `demo-observed`, `demo_observed_on` 2026-10-22 (new constant `DEMO_GTD_PROBE_DATE`), note names run 20261022T120055Z, case `gtd_min_lifetime_boundary` and the evidence file; the 599 s rejection and the 601 s acceptance are quoted from that file.

## Decision recorded for the owner: one deviation from the literal instruction

The instruction limits the listing read to a never-confirmed stop. Reading the code showed a direct consequence that would have made the approved change unsafe: a stop confirmed only by the listing would be supervised on the next step by a by-id query that, in the Demo lag window, still answers -2013, and `_supervise_stop` / `_confirm` would read that as "confirmed and lost" and close a protected position (D077 branch). So `_cross_check_stop` also applies to a stop whose by-id query has never answered found=True (`tracked.stop_by_id_seen`, set on the first found=True answer and for plans restored with a confirmation). Once a by-id query has shown the stop, nothing changes: D077 is exactly as before, no listing is read, a lost stop is never re-placed (test `test_a_stop_confirmed_by_its_id_and_later_lost_is_never_replaced` asserts zero listing reads). If the owner prefers the literal scope, the one `if tracked.stop_confirmed_at is not None and tracked.stop_by_id_seen` guard in `_cross_check_stop` becomes `if tracked.stop_confirmed_at is not None`, and the lag-window false loss returns.

## Tests and RED evidence (honest)

Each failing test was seen failing before its fix.

- WR-A1: `test_a_retry_after_a_failed_finalize_write_closes_without_a_journal_conflict` failed with `('appr-1', 'JOURNAL_FAILED')` kept; `test_a_retry_after_a_failed_ack_write_acks_without_a_journal_conflict` failed (not acked). The third new test (same observation replayed is one row) passed before the fix and is a regression guard.
- WR-A2: 9 of the 10 tests in `tests/test_emergency_close_gate_refusal.py` failed (`CLOSE_FAILED` / `POSITION_READ_FAILED` instead of `NOT_SENT`). `test_a_non_refusal_failure_of_the_position_read_is_still_a_failed_close` passed before and after (it guards the type-only rule: a RuntimeError whose message talks about a rate-limit pause stays `POSITION_READ_FAILED`).
- WR-A3: `test_a_filled_entry_with_two_flat_reads_cancels_the_legs` and `test_a_partly_filled_entry_that_can_still_fill_keeps_the_legs_with_its_own_reason` failed (`ENTRY_NOT_TERMINAL`, legs kept). The other two new tests passed before (they pin the unchanged keep paths).
- `-5040`: 6 tests failed (required-code table, per-kind classification, metadata, observed list, the new row test).
- Stop confirmation: 10 of the 11 tests in `tests/test_protection_demo_shapes.py` failed. The behavior ones failed on state (`UNPROTECTED` instead of `PROTECTED`, `2 == 1` placements, no listing read); some of the ten failed first on the new attribute names (`stop_by_id_seen`, `stop_exists_unconfirmed`), which is weaker evidence for those. `test_when_neither_read_ever_shows_the_stop_there_is_one_attempt_per_step_then_b2` passed before (bounded behavior is unchanged).

Verification actually run (TRADING_CI_STRICT=1, TEST_DATABASE_URL set from the environment, no full suite): tests/test_intent_recovery_unknown_entry.py, test_intent_recovery.py, test_intent_recovery_pg.py, test_emergency_close_gate_refusal.py, test_emergency_market_close.py, test_emergency_close_filters.py, test_execution_emergency.py, test_manual_controls.py, test_drills.py, test_exchange_errors.py, test_cancel_verification.py, test_protection_branches.py, test_protection_demo_shapes.py, test_pending_actions.py, test_protection_supervision.py, test_protection_stop_lost.py, test_execution_manager.py, test_execution_attach.py, test_stream_records.py, test_phase18_gate.py, test_phase19_gate.py, test_phase20_gate.py, test_persistence_exit_evidence_pg.py: all passed. The full set of 34 files that build a protection rig also passed (4 skips, docker/infrastructure). `uv run mypy src` clean (235 files), `uv run ruff check` clean, `uv run ruff format --check` clean (730 files), `uv run python scripts/verify_decision_alignment.py all` ALL_PASS.

## Pins changed

- `tests/test_manual_controls.py`: `test_a_filled_entry_with_a_flat_position_keeps_the_legs` (pinned the bug) replaced by `test_a_filled_entry_with_two_flat_reads_cancels_the_legs` plus the keep-path and partial tests.
- `tests/test_drills.py` and `tests/fixtures/phase8/drill_log/expected.json`: the `manual_close` drill over a filled entry and a position closed outside now ends `safe_mode_entered` (the control removes the legs, nothing is left to sweep) instead of `orphan_swept`. Golden outcome index 6 changed by hand (there is no generator for this fixture). The orphan-swept rehearsal is kept by a variant where the control's first position read fails (`READ_FAILED`, legs kept, the sweeper cancels them); its name still starts with the prefix `tests/test_phase20_gate.py` pins (`test_manual_close_drill_orphan_variant_sweeps_the_legs_that_stayed`), so the gate file is unchanged. The auto-cancel variant now asserts three cancel calls (the control's, answered like an absent order) instead of none.
- `tests/test_exchange_errors.py`: `_EXPECTED_BY_CODE` gains `-5040`; the demo-observed list gains `-5040` with its own date (2026-10-22).
- `tests/test_protection_branches.py`: the call-sequence test of the same-id re-place now includes the listing read between the by-id query and the re-place; module docstring gains the B2/B3 table.
- No gate file (`test_phase18/19/20_gate.py`) was edited.

## Deviations from Plan

**1. [Rule 2 - correctness] The listing cross-check also covers a stop confirmed only by the listing.** See "Decision recorded for the owner" above. Files: `src/execution/protection.py`.

**2. [Rule 3 - blocking] `files_modified` of the PLAN did not list `tests/test_drills.py` and `tests/fixtures/phase8/drill_log/expected.json`.** WR-A3 changes the manual_close drill outcome, so both had to change. Commit 7e8e0ba9 and 0ac58514.

**3. IN-A3 left as is.** The two `register_resting_entry` failure paths discard the `CancelVerdict`. Acting on `FILLED_OR_PARTIAL` or `STILL_OPEN` needs a new SAFE_MODE reason (GLOSSARY 9.4 and the reason pins), an alert or a journal event: not a two-line change. Left for the plan that wires the hand-off (Phase 24); no finding was rejected as wrong. WR-A1, WR-A2 and WR-A3 were each verified against the source before changing anything and all three hold as written (WR-A1 additionally by the RED test).

**4. Fix shape for WR-A1 differs from the review's three suggestions.** A per-observation content-hash id was chosen (one extra append-only evidence row per failed attempt) instead of a stored first-observation time (lost on a restart) or reading the stored row back (the `JournalLike` surface has `record` only).

## Findings for later plans

- Documents: `EXECUTION_SPEC.md` (D-09 line), `RUNBOOK.md` section 3 and `docs/SOURCES.md` could name the listing confirmation, the `-4116` meaning and the `-5040` row; the owner's decision record (a DECISIONS row for the listing rule and `-5040`) is not written (docs/DECISIONS.md is not touched by this plan).
- `ProtectionAdapter` now needs `snapshot_open_algo_orders`; the Phase 24 composition passes the real adapter, which has it.
- The Demo lag was only observed for the by-client-id algo query right after placement (`ro_query1_by_algo_id` by algo id answered at once). Whether the by-client-id index catches up inside one coordinator step, and how long it lags, is `[NOT_TESTED]`; the listing makes the answer independent of it.
- The orphan sweeper does not treat the legs of a plan whose entry still rests as orphans (compare), so a partially filled uncancellable entry plus a flat position leaves the legs to the entry-terminal path only; unchanged by this plan.

## Known Stubs

None.

## Threat Flags

None. The listing read is a signed REST read through the same gated adapter as the existing reads; a gate refusal makes the stop reading UNREADABLE (no re-place). No new endpoint, auth path or schema.

## Self-Check: PASSED

All thirteen files named under key-files exist; the seven commits (1210b4e2, f2abb37d, 5d22c30d, f5c28bc2, 7e8e0ba9, 0ac58514, a8a49d4f) are on branch p20-27.
