base: f5ee61addb14f4ec58ed62eaee889f9880a135cd

---
phase: 18-user-data-stream-error-taxonomy
plan: 26
subsystem: exchange error taxonomy (src/domain/exchange_errors.py)
status: complete
tags: [binance, error-taxonomy, EXEC-02, EXEC-01, D-09, D-10, D-11, D-17, owner-decision-2026-10-17]
requires:
  - 18-01 (SOURCES Phase 18 section)
  - 18-05 (ERROR_CODE_TABLE)
  - 18-21 (the open list of codes observed by the probe and not in the table; the open -1125 labelling)
provides:
  - decisions/18-DEC-TAXONOMY-CODES.md (the owner's decision of 2026-10-17, its evidence, the open items)
  - evidence/18-error-code-page-reread-20261017.txt (committed byte-for-byte)
  - ERROR_CODE_TABLE entries -1106, -4016, -4024; the -1125 provenance; CodeEntry.read_date per entry; ERROR_TABLE_REREAD_DATE; DEMO_SMOKE_DATE
  - tests/test_exchange_error_rejections.py
affects:
  - plan 18-25 (also edits docs/SOURCES.md, other rows; it must run after this plan)
  - Phase 19/20 consumers (open items a to d below)
key-files:
  created:
    - .planning/phases/18-user-data-stream-error-taxonomy/decisions/18-DEC-TAXONOMY-CODES.md
    - .planning/phases/18-user-data-stream-error-taxonomy/evidence/18-error-code-page-reread-20261017.txt
    - tests/test_exchange_error_rejections.py
  modified:
    - src/domain/exchange_errors.py
    - tests/test_exchange_errors.py
    - tests/test_phase18_gate.py
    - docs/SOURCES.md
    - .planning/phases/18-user-data-stream-error-taxonomy/18-TRACEABILITY.md
    - .planning/phases/18-user-data-stream-error-taxonomy/18-VALIDATION.md
decisions:
  - "No DECISIONS.md row: no runtime behavior changes (D055 stays OPEN, D-17); next free number at planning time was D077"
metrics:
  completed: 2026-10-18
actuals:
  tokens: 19000
  tasks: 3
  commits: 5
plan_head_before: f5ee61addb14f4ec58ed62eaee889f9880a135cd
plan_head_after: 58df84c7840fd3fa33e50e948775779b2203dc17
---

# Phase 18 Plan 26: -1106, -4016, -4024 and the -1125 provenance Summary

The owner's decision of 2026-10-17 is on record and in the table: -1106, -4016 and -4024 are REJECTED_DEFINITIVE on PLACEMENT only (UNKNOWN_EXCHANGE_ERROR on every other call kind), documented on the page re-read of 2026-10-17, Demo-observed on 2026-10-16 for -1106 and -4016 and not for -4024; -1125 keeps INVALID_LISTEN_KEY on LISTEN_KEY and now carries its Demo (smoke) provenance. A rejected protective order is proven, on the real manager path, to stay unprotected (ENTRY_WITHOUT_PROTECTIVE, SAFE_MODE). No blocker was hit.

## Commits (all on develop, explicit paths, nothing pushed)

| Commit | Message | Content |
|---|---|---|
| d881ab2 | docs(18-26): record the 2026-10-17 re-read of the error-code page | the evidence file, alone (LF-normalized sha256 equals the pinned fefa3b36...c520 before the commit) |
| bc702da | docs(18-26): record the owner's taxonomy decision of 2026-10-17 | decisions/18-DEC-TAXONOMY-CODES.md, alone |
| 3ee5b84 | feat(18-26): -1106 is REJECTED_DEFINITIVE on placement; per-entry read date | Task 1: table row, mechanism, SOURCES segment, tests |
| 3e901e7 | feat(18-26): -4016 and -4024 are REJECTED_DEFINITIVE on placement; -1125 provenance | Task 2: two rows, -1125 note, SOURCES segment, tests |
| 58df84c | test(18-26): phase 18 gate inventory, traceability and validation additions | Task 3: gate inventory (additions only), 18-TRACEABILITY.md subsection, 18-VALIDATION.md rows 18-26-01 to 03 |

## Table change

- `ERROR_TABLE_REREAD_DATE = "2026-10-17"`, `DEMO_SMOKE_DATE = "2026-10-16"`; `_entry(..., read_date=...)` keyword-only, default `ERROR_TABLE_READ_DATE`; `CodeEntry.__post_init__` validates `read_date` as an ISO date.
- -1106 PARAM_NOT_REQUIRED: documented, read 2026-10-17, demo_observed_on 2026-10-16; never POSITION_MODE; page text and Demo text kept apart; nautilus_trader issue 4231 only as a secondary reference.
- -4016 PRICE_HIGHTER_THAN_MULTIPLIER_UP: documented, read 2026-10-17, demo_observed_on 2026-10-16; page wording and the Demo wording ("Limit price can't be higher than 86305.10.") kept apart; refreshing mark price and filters is the consumer's job.
- -4024 PRICE_LOWER_THAN_MULTIPLIER_DOWN: documented, read 2026-10-17, no demo_observed_on; the note says the table must not assume a snapshot was refreshed.
- -1125: mapping unchanged; the "assumed" sentence replaced by "observed on Demo (smoke)" with the reference evidence/18-smoke-check.txt item f; demo_observed_on 2026-10-16; read_date 2026-10-17.
- Every other entry keeps read_date 2026-10-16. No other code was added (-4131, -4183, -4184 stay UNKNOWN_EXCHANGE_ERROR). The module is still stdlib-only, no float, no clock.
- docs/SOURCES.md: one row changed (one line, +1/-1); first cell byte-identical; cells 2, 3 and 4 gained the "Re-read 2026-10-17" segment.

## RED outputs

- Task 1 (unchanged tree): `tests/test_exchange_error_rejections.py`: 1 failed, 2 passed (the classification test failed: `classify(-1106, PLACEMENT)` was UNKNOWN_EXCHANGE_ERROR; the two manager-branch runs, recording double and real SafeModeController, passed). `tests/test_exchange_errors.py`: collection error, `ImportError: cannot import name 'ERROR_TABLE_REREAD_DATE'`.
- Task 2 (Task 1 tree): `tests/test_exchange_error_rejections.py`: 6 failed, 21 passed (the 6 are the BAD_REQUEST and NOT_FOUND classification of -4016 and -4024 and `test_safe_mode_eligible_is_false_but_the_manager_branch_still_fires[-4016, -4024]`, which fail only at its first line, the taxonomy assertion). `tests/test_exchange_errors.py`: 18 failed, 267 passed (the -4016 and -4024 table, metadata, demo-observed list, read-date, note, 4-code SOURCES tie tests).

## Green characterization runs (Task 2, on the Task 1 tree, before the -4016/-4024 rows existed)

Passed without any source change, as the plan expects: the adapter single-attempt tests (3 codes x 2 methods = 6), the attach tests (STOP_LOSS x 3 codes, TAKE_PROFIT_1 for -4016), the three no-retry tests, the manager-branch tests for the three codes (SAFE_MODE entered, one protective call, entry cancelled), and the entry-rejection sequence tests for -4016 and -4024 (`get_position_mode, place_entry, query_order_by_client, place_entry, query_order_by_client`, identical `place_entry` kwargs, no protective call, no SAFE_MODE, reason EXCHANGE_CONSTRAINT). No test showed a rejected protective order treated as protected.

## Tests changed on purpose (reason for every item: owner decided 2026-10-17)

In `tests/test_exchange_errors.py`, none weakened (each replaced by an equal or stronger assertion):
- `_EXPECTED_BY_CODE` gained -1106, -4016, -4024 (so `test_table_has_exactly_the_required_codes` and `test_code_classifies_per_call_kind` follow).
- `test_table_entry_metadata`: read date is the per-code expected date (`_expected_read_date`, 2026-10-17 for the four owner codes, 2026-10-16 otherwise).
- `_PROBE_OBSERVED_NOT_IN_TABLE` and the assertions that -1106 and -4016 stay UNKNOWN were removed; the probe answers moved into `_PROBE_OBSERVED_IN_TABLE`, and a `_SMOKE_OBSERVED_IN_TABLE` holds -1125. The "stays UNKNOWN" check is now `test_codes_outside_the_owner_decision_stay_unknown` (-4131, -4183, -4184, both table classes, all call kinds).
- `test_demo_observed_codes_are_exactly_the_probe_observed_codes_in_the_table`: the exact list is `[-4509, -4116, -4016, -2021, -2013, -2011, -1125, -1106]` and -4024 is not in it.
- `test_probe_answers_classify_as_the_probe_check_file_says`: also checks the smoke answer.
- `test_a_demo_observation_does_not_relabel_a_documented_code`: gained -1106, -4016, -4024, -1125 as documented.
- `test_read_date_is_the_latest_checked_on_date_of_the_error_code_row`: the latest date of the cell equals `ERROR_TABLE_REREAD_DATE`, the first read date is still in the cell and the section.
- `test_reread_codes_match_the_sources_row`: split on the marker "Re-read 2026-10-17" (occurs once); codes before it equal the codes whose note says "re-read 2026-10-16" plus -4509; codes after it equal the codes whose note says "re-read 2026-10-17" and the codes whose read date is `ERROR_TABLE_REREAD_DATE`.

Added tests (new): `test_entry_read_date_defaults_to_the_first_read_and_can_be_overridden`, `test_code_entry_validates_read_date`, `test_only_the_owner_codes_carry_the_second_read_date`, `test_error_code_row_keeps_one_row_and_records_the_second_read`, `test_1106_entry_keeps_page_and_demo_wording_apart`, `test_4016_entry_keeps_page_and_demo_wording_apart`, `test_4024_entry_is_documented_and_not_observed_on_demo`, `test_1125_keeps_its_mapping_and_records_the_smoke_observation`, `test_sources_row_names_all_four_codes_after_the_marker_and_keeps_the_demo_wording_apart`, and the 27 tests of `tests/test_exchange_error_rejections.py`.

## Owner points OD-1 to OD-6 and the proving tests

- OD-1 (-1106): `test_exchange_error_rejections.py::test_tracer_1106_classifies_rejected_definitive_on_placement_only`, `test_each_owner_code_classifies_rejected_definitive_on_placement_only[-1106]`, `test_exchange_errors.py::test_1106_entry_keeps_page_and_demo_wording_apart` (note content, never POSITION_MODE for any call kind).
- OD-2 (-4016): `test_each_owner_code_classifies_rejected_definitive_on_placement_only[-4016]`, `test_4016_entry_keeps_page_and_demo_wording_apart`, `test_entry_rejection_sequence_is_unchanged_by_the_table[-4016]`.
- OD-3 (-4024): `test_each_owner_code_classifies_rejected_definitive_on_placement_only[-4024]`, `test_4024_entry_is_documented_and_not_observed_on_demo` (no demo_observed_on), `test_demo_observed_codes_are_exactly_the_probe_observed_codes_in_the_table`.
- OD-4 (-1125): `test_exchange_errors.py::test_1125_keeps_its_mapping_and_records_the_smoke_observation` ("assumed" gone, smoke item f cited, demo_observed_on 2026-10-16, mapping unchanged).
- OD-5 (no other code, three inputs, no message text): `test_table_has_exactly_the_required_codes`, `test_codes_outside_the_owner_decision_stay_unknown`, `test_normalizer_never_reads_message_text`, `test_taxonomy_is_pure_stdlib_no_float_no_clock`, and the "different message text changes nothing" loop inside the classification tests.
- OD-6 (tests): `test_no_owner_code_is_retry_eligible_for_any_call_kind`, `test_adapter_makes_one_sdk_call_per_placement_and_reraises_unchanged` (6 cases: one SDK call, no sleep, same exception object, gate unrestricted, drift hook not called), `test_tracer_1106_on_the_protective_stop_is_entry_without_protective[recording_double, real_controller]` and `test_safe_mode_eligible_is_false_but_the_manager_branch_still_fires` (the REAL branch of src/execution/manager.py: ENTRY_WITHOUT_PROTECTIVE, SAFE_MODE entered, entry cancelled by `cancel_normal_order` with journal phases pre_cancel/post_cancel, stop-loss intent UNKNOWN and not ACKED, follow-up plan RECONCILIATION_REQUIRED with zero adapter calls), `test_rejected_stop_loss_in_attach_is_entry_without_protective`, `test_rejected_take_profit_in_attach_is_entry_without_protective`, `test_entry_rejection_sequence_is_unchanged_by_the_table`.

## Gate run (final tree, HEAD 58df84c, PostgreSQL reachable at TEST_DATABASE_URL)

- `uv run pytest -m "not docker" tests/test_phase18_gate.py tests/test_exchange_error_rejections.py tests/test_exchange_errors.py -x -rs`: exit 0 (337 passed)
- `TRADING_CI_STRICT=1 uv run pytest -m "not docker" -q -rs`: exit 0; 10303 passed, 6 skipped, 0 failed (counted from the progress lines because this repo's pytest config hides the summary line). The 6 skips are the Windows platform skips: symlinks (1), NTFS file modes (1), deploy heartbeat file modes (4). No PostgreSQL test was skipped.
- `uv run python scripts/verify_decision_alignment.py all`: exit 0, ends `ALL_PASS all`
- `uv run mypy src`: exit 0 (no issues in 202 source files)
- `uv lock --check`: exit 0 (Resolved 60 packages)
- `uv run ruff check`: exit 0 (All checks passed)
- `uv run ruff format --check`: exit 0 (629 files already formatted)
- Task verify blocks: Task 1 set (5 test files) 499 passed; Task 2 set (12 test files) 939 passed; plus the smaller sets above.
- `git diff --stat f5ee61a..HEAD` over `src/execution src/adapters scripts params tests/support tests/fixtures docs/DECISIONS.md .planning/STATE.md .planning/ROADMAP.md` and the three recorded evidence JSON files prints nothing. `git diff --name-only f5ee61a..HEAD` lists exactly the nine declared files (plus this SUMMARY after its commit).

## Codes observed by the probe and not in the table

None left (the two of 18-21, -1106 and -4016, are decided). -4131, -4183, -4184 are listed by the page and not added.

## Open items (recorded in the decision file, not implemented; follow-up for Phase 19 and 20)

- (a) The consumer refreshes mark price and filter data after -4016 or -4024 before any later order decision and fails closed if it cannot; every new order after a rejection needs the normal human approval flow.
- (b) A consumer must not derive SAFE_MODE for a rejected protective order from `safe_mode_eligible` (these codes are not SAFE_MODE-eligible by the taxonomy; the manager still enters SAFE_MODE on any unconfirmed protective leg).
- (c) The manager's bounded query-first entry re-send (`_ENTRY_MAX_ATTEMPTS`, CR-09) does not consult the taxonomy: after a -4016 or -4024 on the ENTRY the same prices are sent once more after a probe that finds the order absent (pinned by `test_entry_rejection_sequence_is_unchanged_by_the_table`). Phase 19/20 decide whether the manager classifies and stops on REJECTED_DEFINITIVE.
- (d) -4131, -4183, -4184 are not added.

D055 stays OPEN (D-17); no DECISIONS row was written; if the owner wants one the next free number must be recomputed (D077 at planning time).

## Deviations from Plan

None in behavior or scope. Notes:
- The commits are on `develop` at the owner's explicit instruction (the plan's HEAD-safety text for agent branches does not apply to this session; no force-move of any ref was done).
- Task 1 RED for `tests/test_exchange_errors.py` was a collection ImportError (the new constants did not exist) rather than individual failing tests; Task 2 RED has individual failures.
- The decision file cites the origin of the open list as `18-21-SUMMARY.md` in the phase directory (the plan text said `evidence/18-21-SUMMARY.md`, which is not where the file is).
- Docker Desktop was running (container trading-postgres-1 healthy) when Task 3 started, so the strict gate ran with PostgreSQL; the precondition check passed.
- `.planning/STATE.md` and `.planning/ROADMAP.md` were not updated: the plan lists them as files not to edit (the stale ROADMAP Phase 18 status lines are left for the phase-closing step, as the owner answered).
- Untracked items (`.gsd/`, `.planning/milestone.lock`, `package.json`, `package-lock.json`, `docs/research/experiments/research-run-1-v2-3-0/`) were never staged or touched.

## Known Stubs

None.

## Threat Flags

None (no new network, auth or file-access surface; T-18-80 to T-18-85 mitigations are the tests above).

## Self-Check: PASSED

- Files exist: 18-DEC-TAXONOMY-CODES.md, 18-error-code-page-reread-20261017.txt, tests/test_exchange_error_rejections.py (verified in the tree and in `git ls-files`).
- Commits exist: d881ab2, bc702da, 3ee5b84, 3e901e7, 58df84c.
