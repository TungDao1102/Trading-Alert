---
phase: 16-paper-runtime-composition
plan: 16
subsystem: paper-runtime / durable state
tags: [runtime-state, journal, deterministic-ids, restart-restore, postgresql, q-j, idempotent-replay]

requires:
  - phase: 16-paper-runtime-composition
    provides: "plan 16-08: RuntimeEventType, INTERVAL_MS vocabulary; plan 16-15: the RuntimeRecordLike payload-key contract"
provides:
  - "src/paper/runtime_state.py: RuntimeRecord, runtime_event_id, RuntimeStatePort, InMemoryRuntimeState, RuntimeRecordConflict (pure, no SQLAlchemy)"
  - "src/persistence/paper_runtime_state.py: PgRuntimeState, the port on journal_events rows (Q-J journal-only)"
  - "decisions/16-DEC-Q-J.md committed: option journal-only, decided by user, 2026-10-09"
affects: [16-24 bar pipeline records, 16-26 live loop tick stats, 16-29 restart and warm-up, 16-22 runtime composition, evidence exporter]

actuals:
  tokens: 12000
  tasks: 3
  commits: 5
plan_head_before: 9bbbc131bac394251689ed527c444ef103c8fb60
plan_head_after: 319a5d581448891bd91ec0aa4bb5b50d8ecf2d5f
commits: 5

tech-stack:
  added: []
  patterns:
    - "One behaviour contract written as contract_* functions over a port factory, run against the in-memory and the PostgreSQL implementation so they cannot drift"
    - "Ids are correlated_event_id over a key built only from the epoch, the pair and the bar close (or tick time and batch_seq); the clock never enters an id"
    - "Record payloads are normalised once with src.domain.canonical (Decimal and datetime to text, float refused) and deep-frozen, so in-memory and database records round-trip to equal values"

key-files:
  created:
    - src/paper/runtime_state.py
    - src/persistence/paper_runtime_state.py
    - tests/test_paper_runtime_state.py
    - tests/test_paper_runtime_state_pg.py
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-Q-J.md
  modified: []

key-decisions:
  - "Q-J (user, 2026-10-09, 'journal-only'): runtime state is journal rows only. No Alembic migration, no table, no change to src/db/models.py or src/persistence/system_state.py"
  - "PAPER_GAP is keyed on payload expected_close_utc, not on when it was detected, so a gap seen before and after a restart is one record; a second record with another reason is a RuntimeRecordConflict"
  - "Replay identity is event type, epoch, pair and payload; occurred_at_utc is not compared (same rule as PgJournalStore, a redelivery carries a new delivery time)"
  - "A STOP and a START at the same instant resolve to the START as the latest marker, matching the ordering rule in src/paper/coverage.py"

patterns-established:
  - "Pattern: PG ports built on the journal translate JournalConflict to the port's own conflict error and keep payload contents out of the message"

requirements-completed: [PAPER-01]

coverage:
  - id: D1
    description: "Every runtime record type is written through one port with a deterministic id keyed on the epoch and the bar close (tick stats: tick time and batch_seq), never on the wall clock"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_runtime_state.py#test_bar_event_id_is_a_pure_function_of_epoch_pair_close_and_type"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_state.py#test_ids_do_not_read_the_wall_clock"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_state.py#test_the_module_never_hashes_the_wall_clock_into_an_id"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_state.py#test_in_memory_state_meets_the_contract[contract_tick_stats_ids_use_the_batch_sequence]"
        status: pass
    human_judgment: false
  - id: D2
    description: "Replaying a record is a no-op and different content under the same id is a conflict, in memory and on PostgreSQL; replaying a whole simulated session inserts zero rows"
    requirement: PAPER-01
    verification:
      - kind: integration
        ref: "tests/test_paper_runtime_state_pg.py#test_replaying_a_full_session_inserts_zero_rows_and_raises_nothing"
        status: pass
      - kind: integration
        ref: "tests/test_paper_runtime_state_pg.py#test_a_conflict_is_the_port_error_not_the_journal_error"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_state.py#test_in_memory_state_meets_the_contract[contract_replay_is_a_no_op_and_different_content_conflicts]"
        status: pass
    human_judgment: false
  - id: D3
    description: "After a restart a new port instance returns the last close per (symbol, interval) and the latest runtime marker of the epoch"
    requirement: PAPER-01
    verification:
      - kind: integration
        ref: "tests/test_paper_runtime_state_pg.py#test_a_restart_restores_the_closes_and_the_marker_from_the_database"
        status: pass
      - kind: integration
        ref: "tests/test_paper_runtime_state_pg.py#test_pg_state_meets_the_same_contract_as_the_in_memory_state"
        status: pass
    human_judgment: false
  - id: D4
    description: "Where durable state lives is the user's Q-J decision and no schema change happened without it"
    requirement: PAPER-01
    verification:
      - kind: other
        ref: "git diff --stat 9bbbc13..HEAD shows no change under src/db and no change to src/persistence/system_state.py"
        status: pass
    human_judgment: false
  - id: D5
    description: "That the payload keys the runtime producers (plans 16-24, 16-26, 16-29) will actually write match the RuntimeRecordLike contract, including batch_seq for PAPER_TICK_STATS and expected_close_utc for PAPER_GAP"
    requirement: PAPER-01
    verification: []
    human_judgment: true
    rationale: "The producers do not exist yet. runtime_event_id refuses a PAPER_TICK_STATS record without an integer batch_seq and a PAPER_GAP without payload expected_close_utc, so a mismatch fails loudly at the first write, but the producing plans must be checked against this when they land."

duration: 12min
completed: 2026-10-09
status: complete
---

# Phase 16 Plan 16: Runtime state port Summary

**One storage port for restart-surviving runtime state: frozen `RuntimeRecord` values with deterministic ids (epoch plus bar close, or tick time plus batch_seq, never the clock), an in-memory reference implementation, and `PgRuntimeState` that stores every record as a `journal_events` row through `PgJournalStore.record`, exactly as the user decided in Q-J ("journal-only") with no migration.**

## Performance

- **Duration:** about 12 min (2026-10-09, roughly 14:48Z to 14:59Z; the start time was taken after the initial reading)
- **Tasks:** 3 (Task 1 tracer, Task 2 the Q-J decision resolved by the user before this run, Task 3 auto; Tasks 1 and 3 TDD)
- **Files:** 4 created in `src`/`tests`, plus the decision record committed

## Accomplishments

- Tracer (Task 1): `RuntimeRecord` (event type from the vocabulary, epoch, optional pair, UTC time, canonicalised and deep-frozen payload), `RuntimeRecord.bar_processed` (time is the bar close), `runtime_event_id`, `RuntimeStatePort`, `InMemoryRuntimeState`, `RuntimeRecordConflict`. Ids use `correlated_event_id(prefix="paper", ...)` over `paper:<epoch>:<symbol>:<interval>:<close_ms>` for bar-keyed records, `paper:<epoch>:tick:<at_ms>:<batch_seq>` for tick stats and `paper:<epoch>:runtime:<at_ms>` for markers; the event type is part of the hash. `content_hash_event_id` is never used (an AST test asserts it and every clock-read name are absent).
- Task 2: the user chose `journal-only`; the record `16-DEC-Q-J.md` (option, "decided by: user", date, words verbatim) was committed unchanged (`9735b08`).
- Task 3: `PgRuntimeState(db)` writes through `PgJournalStore.record` with entity type "PaperRuntime", translates `JournalConflict` to `RuntimeRecordConflict` (field names only, no payload text), and reads with bounded queries: `last_close_by_pair` is one `DISTINCT ON (entity_id)` row per pair, `latest_runtime_marker` reads at most two rows, `records` filters by event type. The epoch prefix `paper:<epoch>:` is matched literally (LIKE wildcards escaped; a test with epochs `e_1`, `eX1` and `e%` proves isolation).
- The same seven `contract_*` behaviours run against both implementations (replay, conflict, close time, tick ids, full-session replay, filtering and order, payload round trip).

## RED Evidence

- **Task 1** (`f04fa31`): `ModuleNotFoundError: No module named 'src.paper.runtime_state'` at collection.
- **Task 3** (`c3269c0`): `ModuleNotFoundError: No module named 'src.persistence.paper_runtime_state'` at collection.

## Task Commits

1. **Task 1 (tracer): port, ids, in-memory implementation** - `f04fa31` (test, RED), `d0581b0` (feat, GREEN)
2. **Task 2 (decision Q-J, resolved by the user): `journal-only`** - `9735b08` (docs)
3. **Task 3: PostgreSQL implementation** - `c3269c0` (test, RED), `319a5d5` (feat, GREEN)

Tracer gate (auto mode): the tracer `<verify>` was re-run end to end after Task 1 and passed; expansion continued.

**Plan metadata:** committed separately (docs: complete plan).

## Files Created

- `src/paper/runtime_state.py` - port, record, ids, in-memory implementation (stdlib plus `src.domain.canonical`, `src.domain.journal`, `src.paper.vocabulary`; no SQLAlchemy)
- `src/persistence/paper_runtime_state.py` - `PgRuntimeState` (not re-exported from `src/paper/__init__.py`, which promises no SQLAlchemy)
- `tests/test_paper_runtime_state.py` - 22 tests (contract run plus id, validation and purity tests)
- `tests/test_paper_runtime_state_pg.py` - 16 tests on disposable `t17_<hex>_test` databases
- `.planning/phases/16-paper-runtime-composition/decisions/16-DEC-Q-J.md` - the user's decision

Files the plan listed only for the other Q-J options (`src/db/alembic/versions/0005_paper_runtime_state.py`, `src/db/models.py`, `src/persistence/system_state.py`) were not touched, as the option chosen needs none of them.

## Decisions Made

See `key-decisions`. For downstream plans:

- **Payload keys (extends the 16-15 contract).** PAPER_BAR_PROCESSED: `source`, `tick_time_utc`, record time is the bar close. PAPER_GAP: `expected_close_utc` (required, ISO UTC) and `reason`; the record time is free (detection time). PAPER_TICK_STATS: integer `batch_seq` (required, per-process counter, not a bool) plus `duration_ms`, `queue_depth_before`, `dropped_total`, `dropped_by_reason`. HEALTH_STATE_CHANGED: `state`, `reason`.
- **Payload values.** `Decimal` and aware `datetime` become canonical text, enums become their value, floats raise `TypeError`, keys must be text. A reader sees ISO strings, not datetimes (the 16-15 readers already accept both).
- **Constraints on text parts.** `epoch_id` (64 chars), `symbol` (32) and `interval` (8) must be non-empty, contain no `:` and fit those lengths so the 128-char journal columns always hold the derived ids.
- **Writers must not reuse a key with other content.** A second PAPER_BAR_PROCESSED for the same close with a different `source` or `tick_time_utc`, or two HEALTH_STATE_CHANGED records in one millisecond with different states, raise `RuntimeRecordConflict`. That is deliberate (fail loudly); a producer that can legitimately re-process a bar must decide which record is the truth before writing.

## Deviations from Plan

None - plan executed as written, with the Q-J decision supplied by the user before execution.

### Plan-shape choices (not defects)

- The shared behaviour bodies live in `tests/test_paper_runtime_state.py` and are imported by the PG test file (no extra helper file).
- `RuntimeRecord.bar_processed` is a small constructor helper that makes "the time of a bar record is the bar close" hard to get wrong.
- `occurred_at_utc` is excluded from replay identity (it matches `PgJournalStore`), so in the rare case of a gap re-recorded with a different detection time the first stored time stays.

## Issues Encountered

- None blocking. Ruff flagged one over-long line in the new module (fixed by `ruff format`).

## Known Stubs

None.

## Known Limitations

- **Restore scans the journal table.** The prefix filter `correlation_id LIKE 'paper:<epoch>:%'` cannot use the plain btree index `ix_journal_events_correlation` under a non-C collation, so each read is a filtered scan of `journal_events` (by entity type and event type). The result size is bounded (one row per pair, two rows, or the epoch's records) but the scan cost grows with the whole journal. That is acceptable for the soak, and an index would be the schema change Q-J ruled out; revisit only if a restart is measured slow.
- **`records()` is not paginated.** It returns the whole epoch (optionally by type); the evidence exporter should pass `event_types`. A 14-day soak is on the order of thousands of rows.
- **Synchronous port.** The runtime must wrap calls in `asyncio.to_thread` (phase 24 item G4-040 stays open).
- **The pre-existing failure** `tests/test_cost_parity.py::test_simulator_and_paper_call_evaluate_risk_with_identical_arguments` (logged in `deferred-items.md`) was not touched and not run here.

## Threat Flags

None. T-16-38 (duplicate or missing rows after a crash) mitigated: deterministic correlated ids, journal `ON CONFLICT DO NOTHING` replay, `RuntimeRecordConflict` on different content, PG replay test inserting zero rows. T-16-39 (schema change without consent) mitigated: the Q-J record exists and no file under `src/db` or `system_state.py` changed. T-16-SC accepted: no package installed, `uv.lock` unchanged.

## User Setup Required

None. The PG tests used the user-supplied disposable `trading_test` server through `TEST_DATABASE_URL` in the command environment only; nothing was written to any file.

## Next Phase Readiness

- Plans 16-22, 16-24, 16-26 and 16-29 can construct `PgRuntimeState(OperationalDatabase(engine))` (or `InMemoryRuntimeState` in tests), write all nine event types through `record`, and restore with `last_close_by_pair(epoch_id)` and `latest_runtime_marker(epoch_id)` (feed `record_close` of the supervisor from the first).
- The evidence plans can pass `port.records(epoch_id)` straight to `src/paper/coverage.py`: `RuntimeRecord` satisfies `RuntimeRecordLike` unchanged.

## Verification

- `TRADING_CI_STRICT=1 TEST_DATABASE_URL=<disposable _test database> .venv/Scripts/python -m pytest tests/test_paper_runtime_state_pg.py tests/test_paper_runtime_state.py -q -p no:cacheprovider -rs`: 38 passed, 0 skipped.
- Also green with the same environment: `tests/test_domain_no_float.py` (the new `src/paper` module is float-scanned through the glob), `tests/test_pg_fixture_guard.py`, `tests/test_paper_coverage.py`, `tests/test_domain_boundary.py`, `tests/test_paper_vocabulary.py`, `tests/test_persistence_journal_pg.py`.
- `ruff check` and `ruff format --check` (479 files) and `mypy src` (167 files) are clean.
- No file was deleted by any commit; no package installed; `uv.lock` unchanged. The whole `pytest -m "not docker"` suite was not run in one process.

## Self-Check: PASSED

- FOUND: src/paper/runtime_state.py, src/persistence/paper_runtime_state.py, tests/test_paper_runtime_state.py, tests/test_paper_runtime_state_pg.py, decisions/16-DEC-Q-J.md
- FOUND commits: f04fa31, d0581b0, 9735b08, c3269c0, 319a5d5
