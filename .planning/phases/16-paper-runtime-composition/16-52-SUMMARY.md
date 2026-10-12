---
phase: 16-paper-runtime-composition
plan: 52
subsystem: paper runtime / restart epoch consistency (gap closure of 16-29-DEV-EPOCH-SCOPED)
tags: [restart, epoch-pin, rev-18, runtime-state-port, cross-epoch, paper-01]

requires:
  - phase: 16-paper-runtime-composition
    provides: "plan 16-29 (check_epoch_consistency, EpochMismatch mapped to exit 6 in main), plan 16-16 (RuntimeStatePort, PgRuntimeState on journal_events)"
provides:
  - "RuntimeStatePort.latest_epoch_pins: every EPOCH_PINNED at the latest pin instant across all epochs, on the in-memory and the PostgreSQL port"
  - "check_epoch_consistency refuses (EpochMismatch, exit 6 before any subscription and before RUNTIME_START) when the latest pin belongs to another epoch or two epochs share the latest pin instant"
  - "shared port contract contract_latest_epoch_pins_is_cross_epoch (runs in memory here and on PostgreSQL through the existing CONTRACTS parametrization)"
affects: [16-31 (owns src/paper/runtime.py, untouched here), 16-40, 16-43 (a stray later EPOCH_PINNED on the soak database makes every restart refuse with exit 6, intended)]

requirements-completed: []

status: complete
actuals:
  tokens: 9000
  tasks: 2
  commits: 3
plan_head_before: d44e6e076477018c7595f21290508b306b467b1c
plan_head_after: 62148e61010314b66fb9acc4da998df3cbd9397a
commits: 3

tech-stack:
  added: []
  patterns:
    - "One deliberately cross-epoch journal query (entity PaperRuntime, event type EPOCH_PINNED, rows at the maximum instant of that subset); every other port read stays epoch-prefix scoped"

key-files:
  created: []
  modified:
    - src/paper/runtime_state.py
    - src/persistence/paper_runtime_state.py
    - src/paper/restart.py
    - tests/test_paper_runtime_restart.py
    - tests/test_paper_runtime_loop.py
    - tests/test_paper_runtime_state.py

key-decisions:
  - "The cross-epoch check runs first and the unchanged epoch-scoped field comparison second, so a differing pin record still reports 'differs' and an empty state still reports 'no EPOCH_PINNED'"
  - "A tie at the latest instant between the pin file's epoch and another epoch is a refusal (the pin file is not the unique latest pin), worded separately from a plainly later foreign pin"
  - "No migration, index or schema change (Q-J, D-04); no constant, threshold, parameter set or strategy_version change"

patterns-established:
  - "Port methods added to RuntimeStatePort need a delegating line in test doubles (BlockingState) and are proven once as a contract for both ports"

coverage:
  - deliverable: "a restart under a later pin of another epoch exits 6 before any subscription and RUNTIME_START"
    verification:
      - {kind: pytest, ref: "tests/test_paper_runtime_restart.py::test_a_restart_under_a_later_pin_of_another_epoch_exits_6_before_any_subscription", status: pass}
      - {kind: pytest, ref: "tests/test_paper_runtime_restart.py::test_check_epoch_consistency_is_cross_epoch", status: pass}
      - {kind: pytest, ref: "tests/test_paper_runtime_restart.py::test_negative_control_the_refusal_comes_from_the_cross_epoch_answer", status: pass}
    human_judgment: false
  - deliverable: "latest_epoch_pins gives the same answer on the in-memory port and on PostgreSQL"
    verification:
      - {kind: pytest, ref: "tests/test_paper_runtime_state.py::test_in_memory_state_meets_the_contract[contract_latest_epoch_pins_is_cross_epoch]", status: pass}
      - {kind: pytest, ref: "tests/test_paper_runtime_state_pg.py (CONTRACTS parametrization), TRADING_CI_STRICT=1", status: not-run}
    human_judgment: false
    rationale: "TEST_DATABASE_URL is not set on this machine; the PostgreSQL statement was only compiled against the PostgreSQL dialect"

duration: ~20 min
completed: 2026-10-12
---

# Phase 16 Plan 52: Cross-epoch pin check on restart Summary

**`RuntimeStatePort.latest_epoch_pins()` (in memory and on PostgreSQL) lets `check_epoch_consistency` refuse a restart whose pin file is not the latest EPOCH_PINNED across all epochs (REV-18), so a superseded trial exits 6 before any subscription and before its RUNTIME_START.**

## Performance

- **Tasks:** 2 of 2 (Task 1 tracer, Task 2 auto; both `tdd="true"`)
- **Files:** 0 created, 6 modified; `src/paper/runtime.py` not touched
- **Commits:** 3 measured (`plan_head_before..plan_head_after`); this SUMMARY commit, if made, is the fourth

## Accomplishments

- **Port query.** `latest_epoch_pins()` is part of the `RuntimeStatePort` protocol. The in-memory answer is every stored EPOCH_PINNED at the maximum `occurred_at_utc`, sorted by `record_sort_key`. The PostgreSQL answer is one bounded read of `journal_events` (entity type `PaperRuntime`, event type `EPOCH_PINNED`, rows equal to the maximum instant of that subset), deliberately not restricted to an epoch prefix, rebuilt with `_record_from_row` and returned in port order. The module docstring states why this one query is cross-epoch. No migration, index or schema change.
- **Cross-epoch check.** `check_epoch_consistency` asks `latest_epoch_pins()` first: a pin of another epoch among the latest ones raises `EpochMismatch` naming that epoch id and the REV-18 rule (worded as a tie when the pin file's own epoch shares the instant). The previous epoch-scoped comparison (missing record, strategy, parameter set, hash, opening time) runs unchanged afterwards. `main` already maps `EpochMismatch` to exit 6 before any subscription and before RUNTIME_START.
- **Contract.** `contract_latest_epoch_pins_is_cross_epoch` is appended to `CONTRACTS`: empty without a pin, a non-pin record is not a pin, the later pin of the other epoch wins, a later record of another type is ignored, a same-instant tie returns both in port order, replaying the pins changes no answer. `tests/test_paper_runtime_state_pg.py` picks it up through its existing parametrization (not edited).

## Task Commits

| Task | Commit | What |
| --- | --- | --- |
| 1 RED | dbc48a0 | test(16-52): RED tracer for the cross-epoch pin check on restart |
| 1 GREEN | b64fc62 | feat(16-52): restart pin check is cross-epoch (latest EPOCH_PINNED across all epochs) |
| 2 RED/characterization | 62148e6 | test(16-52): shared cross-epoch latest_epoch_pins contract for both runtime state ports |

## RED evidence

- **Task 1.** At RED (commit dbc48a0, before any source change) all three new tests failed:
  `test_a_restart_under_a_later_pin_of_another_epoch_exits_6_before_any_subscription` (the old check only read the pin file's own epoch, so the restart started instead of exiting 6), `test_check_epoch_consistency_is_cross_epoch` (no `EpochMismatch` raised for a later or tied foreign pin) and `test_negative_control_the_refusal_comes_from_the_cross_epoch_answer` (`probe.asked` was 0: the check never asked a cross-epoch query). After GREEN they pass and every pre-existing test of the restart, admission, loop and market-inputs files passes unedited (512 tests in the combined collection of the broader run below).
- **Task 2.** The contract passed on the in-memory port at its first run, because Task 1's GREEN already implemented the in-memory answer. Recorded as a characterization of Task 1, as the plan allows (as plan 16-29 did for its replay test). No source correction was needed by Task 2.

## Verification

- `uv run pytest tests/test_paper_runtime_restart.py tests/test_paper_runtime_admission.py tests/test_paper_runtime_loop.py tests/test_paper_market_inputs.py -q -p no:cacheprovider`: all passed.
- `uv run pytest tests/test_paper_runtime_state.py tests/test_paper_runtime_state_pg.py tests/test_paper_runtime_restart.py tests/test_paper_runtime_restart_pg.py -q -p no:cacheprovider -rs`: in-memory tests passed; the PostgreSQL tests are skipped (see NOT RUN).
- `uv run mypy src`: no issues in 179 source files. `uv run ruff check`: all checks passed. `uv run ruff format --check`: 512 files already formatted.
- Full run `uv run pytest -m "not docker"` (no `-x`, PostgreSQL tests skipped): four failures, none in files this plan touches, none an assertion edited by this plan: `tests/test_cost_parity.py::test_simulator_and_paper_call_evaluate_risk_with_identical_arguments` (also fails on the untouched base commit d44e6e0, checked in a throwaway checkout), `tests/test_paper_runtime_pipeline.py::test_backfill_only_batch_extends_history_and_records_one_gap_per_close`, `tests/test_paper_runtime_pipeline.py::test_every_arrival_order_of_one_group_gives_byte_identical_records` and `tests/test_paper_vocabulary.py::test_runtime_event_type_carries_the_tick_stats_record`. The last three concern the `PAPER_HISTORY_BARS` record that plan 16-51 introduced (extra record type in the expected sets); they are outside this plan's scope and are reported to the orchestrator, not fixed (scope boundary).
- The PostgreSQL statement of `latest_epoch_pins` was compiled with the PostgreSQL dialect (`WHERE entity_type = ... AND event_type = ... AND occurred_at_utc = (SELECT max(occurred_at_utc) ... same filter)`); it was not executed.

## NOT RUN

- **Strict PostgreSQL proof:** `TRADING_CI_STRICT=1 .venv/Scripts/python -m pytest tests/test_paper_runtime_state_pg.py tests/test_paper_runtime_restart_pg.py -q -p no:cacheprovider -rs` was NOT RUN: `TEST_DATABASE_URL` is not set in this worktree (no URL was invented). The plan is not complete until the orchestrator runs that command against a disposable PostgreSQL 17 test database and it reports every test passed and 0 skipped.

## Deviations from Plan

None - plan executed as written.

One note on environment, not on scope: the worktree had no `.venv`, so `uv sync --frozen --extra dev` was run first and the checks were run through `uv run`.

## Authentication Gates

None.

## Known Stubs

None.

## Threat Flags

None. T-16-125 is mitigated by the cross-epoch check (PostgreSQL proof pending, see NOT RUN); T-16-126 is accepted as planned (a stray later pin blocks every restart, with the refusal naming the later epoch).

## Self-Check: PASSED

- Modified files exist and `git log --grep="(16-52)" --name-only --format=` lists only this plan's files (no `src/paper/runtime.py`, no migration).
- Commits exist: dbc48a0, b64fc62, 62148e6.
- `requirements-completed` is empty by design: PAPER-01 closes only on real soak evidence (SC9). STATE.md and ROADMAP.md were not touched.
