---
phase: 10-journal-depth-kill-gate-operations
plan: 09
subsystem: adapters
tags: [edge-adapter, analytics, family-registry, fail-closed-loaders, select-only, idempotent-append, parquet, path-confinement, tdd, tracer]

requires:
  - phase: 10-journal-depth-kill-gate-operations
    provides: "10-03/10-06/10-07 pure analytics core (FamilyEvidence/independent_family_ids, evaluate + clock, FamilyGateFacts, ResetRecord, TradeOutcome/OutcomeContext, compute_trade_excursion)"
  - phase: 03-domain-persistence
    provides: "db mappers (journal_from_row and the six entity mappers), JournalEventRow, load_parameter_set registry"
  - phase: 02-data-pipeline
    provides: "Hive-partitioned immutable 1m Parquet store (partition_file, publish_batch)"
provides:
  - "src/adapters/analytics_files.py: scan_family_facts (real registry + family sheets -> FamilyEvidence/FamilyGateFacts), read_protocol_text, load_evidence_file / load_decisions_file / load_universe_file (fail-closed, typed errors), confine_output_dir + REPORTS_ROOT"
  - "src/adapters/analytics_store.py: select_journal_events_stmt, journal_rows_to_events, read_journal_events, read_live_rows (SELECT-only, total-key order, rejects counted), build_append_stmt + append_kill_gate_event (single idempotent write), read_candles (1m Parquet, read-only)"
  - "Fixtures tests/fixtures/phase10/loaders/{evidence_sample,decisions_sample,universe_sample}.json"
affects: [10-10, 10-11, 10-12]

actuals:
  tokens: 22800
  tasks: 3
  commits: 7
plan_head_before: 183de32170f177b41715705e59b979e4909873eb
plan_head_after: f9d5e37ab8935c70339f712dc2ee1519c4d50d34

tech-stack:
  added: []
  patterns:
    - "All analytics I/O sits in two thin edge adapters; src/analytics stays pure (purity + strict-typing guards cover the adapters)"
    - "Loaders raise typed errors that name the offending key or index and carry exception class names only, never values or file contents"
    - "The only write in the phase is one INSERT ... ON CONFLICT (journal_event_id) DO NOTHING built in exactly one function, guarded by an event-type check before any statement exists (AST-tested)"
    - "Async wrappers are tested with fake sessions and a sync-SQLite-backed async facade (no aiosqlite dependency); live PG test is gated on TEST_DATABASE_URL"

key-files:
  created:
    - src/adapters/analytics_files.py
    - src/adapters/analytics_store.py
    - tests/test_analytics_files.py
    - tests/test_analytics_store.py
    - tests/fixtures/phase10/loaders/evidence_sample.json
    - tests/fixtures/phase10/loaders/decisions_sample.json
    - tests/fixtures/phase10/loaders/universe_sample.json
  modified: []

key-decisions:
  - "Families are the params/ directory names; candidate hashes are the load_parameter_set hashes of every non-baseline set; only CANDIDATE experiments whose parameter_set_hash matches map to a family, other CANDIDATE hashes go to unknown_experiment_ids (never guessed), baseline-run experiments are excluded without being listed"
  - "Family sheet hash is sha256 of the content after CRLF-to-LF normalization so the digest equals the committed blob on every checkout"
  - "FamilyEvidence.experiment_ids holds only mapped experiments; a TESTED_* decision naming experiment ids not present in the evidence therefore fails closed with KillGateInputError instead of being padded"
  - "read_live_rows reports rejected counts for all six tables in fixed order (zeros included) so the report can render an explicit no-reject line"
  - "An unreadable Parquet partition file is counted as one rejected unit (never fatal, never guessed); a missing partition contributes nothing"
  - "append_kill_gate_event and the readers are async over AsyncSession; dialect comes from session.get_bind().dialect.name and only postgresql and sqlite are supported"

patterns-established:
  - "Symbol path segments are validated against [A-Z0-9]{5,20} before joining into a partition path"
  - "Reader-purity is proven by source-level tests (no insert/update/delete/text/commit tokens in read functions; exactly one Insert-building function in the module)"

requirements-completed: [JRN-01, GOV-01]

coverage:
  - id: D1
    description: "Tracer: the real params/ registry and docs/research/families sheets yield three independent families (7 slots, distinct sheet hashes, disjoint non-baseline candidate hashes) and evaluate() returns WITHIN_BUDGET on the real repo"
    requirement: GOV-01
    verification:
      - kind: unit
        ref: "tests/test_analytics_files.py#test_tracer_real_repo_scan_feeds_evaluator"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_files.py#test_scan_missing_sheet_breaks_independence"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_files.py#test_scan_unknown_parameter_set_hash_is_listed_never_guessed"
        status: pass
    human_judgment: false
  - id: D2
    description: "Evidence, decisions and universe files load fail-closed into typed objects; output directories are confined to the reports root (.., absolute and symlink escapes refused)"
    requirement: JRN-01
    verification:
      - kind: unit
        ref: "tests/test_analytics_files.py#test_evidence_sample_loads_into_typed_objects"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_files.py#test_decisions_tested_without_required_field_fails_closed"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_files.py#test_confine_rejects_dotdot_traversal"
        status: pass
    human_judgment: false
  - id: D3
    description: "SELECT-only journal/entity reader in total-key order with rejects counted, single idempotent KILL_GATE_EVALUATION append, and read-only 1m candle reader that feeds compute_trade_excursion to identical MFE/MAE"
    requirement: JRN-01
    verification:
      - kind: unit
        ref: "tests/test_analytics_store.py#test_append_kill_gate_event_is_idempotent_on_replay"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_store.py#test_module_has_exactly_one_insert_building_function"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_store.py#test_read_candles_round_trips_through_publish_batch"
        status: pass
    human_judgment: false
  - id: D4
    description: "Append and re-read of a KILL_GATE_EVALUATION event against a live PostgreSQL 17 (ON CONFLICT semantics on the real dialect)"
    requirement: GOV-01
    verification: []
    human_judgment: true
    rationale: "The live-PG integration test is written but skipped without TEST_DATABASE_URL; statement compilation for the postgresql dialect is asserted, but execution against a real server and the symlink-escape confinement test (skipped where symlinks are unavailable) were not run in this environment"

duration: 13min
completed: 2026-09-29
status: complete
---

# Phase 10 Plan 09: Analytics Edge Adapters Summary

**Two thin edge adapters feed the pure analytics core: fail-closed evidence/decision/universe loaders plus a real-repo family scan (registry + 7-slot sheets, no free-text flag), and a SELECT-only journal/entity/candle store with a single idempotent KILL_GATE_EVALUATION append.**

## Performance

- **Duration:** ~13 min (07:32Z to ~07:53Z)
- **Tasks:** 3 (1 tracer + 2 auto), all TDD with a separate RED commit before each GREEN
- **Files:** 2 adapter modules, 2 test modules, 3 fixtures (about 90 KB of source and tests)

## Accomplishments

- Tracer: `scan_family_facts` reads `params/<family>/` and `docs/research/families/<family>.md` and returns the three real families with slots (1..7), three distinct sheet hashes and disjoint non-baseline candidate hashes; `independent_family_ids` accepts all three and `evaluate` on the real repo returns WITHIN_BUDGET with families_tested 0.
- Experiment mapping is by `parameter_set_hash` against CANDIDATE runs only; unknown hashes are listed in `unknown_experiment_ids` and never guessed onto a family.
- `load_evidence_file` / `load_decisions_file` / `load_universe_file` raise typed errors naming only the key/index (no values, no file contents, no connection strings); the committed `docs/research/kill_gate_decisions.json` loads to an empty `DecisionsFile`.
- `confine_output_dir` refuses `..`, absolute escapes, sibling-prefix names and (where creatable) symlink escapes; default is `REPORTS_ROOT` itself.
- `read_journal_events` / `read_live_rows` build and run SELECT statements only, convert through the existing mappers, count malformed rows, and return events in the total key order regardless of row order.
- `build_append_stmt` / `append_kill_gate_event` implement the only write: ON CONFLICT (journal_event_id) DO NOTHING on postgresql and sqlite, refusing any other event type before a statement is built; replay leaves exactly one row.
- `read_candles` reads the immutable per-day 1m Parquet partitions, returns an empty result for missing partitions, and round-trips through `publish_batch` to the same MFE/MAE as direct candles.

## Task Commits

1. **Task 1 RED:** `42c858e` test(10-09): failing real-repo family scan tracer tests
2. **Task 1 GREEN:** `b42179e` feat(10-09): real-repo family scan feeds the kill-gate evaluator
3. **Task 2 RED:** `9fcb0dc` test(10-09): failing evidence, decisions, universe loader and confinement tests
4. **Task 2 GREEN:** `39c8b98` feat(10-09): fail-closed evidence, decisions and universe loaders with output confinement
5. **Task 3 RED:** `2fa30f8` test(10-09): failing store adapter tests for reader, guarded append and candle reader
6. **Task 3 GREEN:** `3cb6c7f` feat(10-09): SELECT-only analytics store reader, guarded kill-gate append and 1m candle reader
7. **Fix:** `f9d5e37` fix(10-09): normalize line endings before hashing family sheets

Tracer gate: the tracer `<verify>` (`pytest tests/test_analytics_files.py -k "tracer or scan"`) was green end to end before expansion (log: tracer verified end-to-end, expanding).

## Files Created/Modified

- `src/adapters/analytics_files.py` - errors, decision/flag/scan dataclasses, `scan_family_facts`, `read_protocol_text`, the three loaders, `confine_output_dir`, `REPORTS_ROOT`.
- `src/adapters/analytics_store.py` - result dataclasses, journal/live readers, append statement builder and appender, candle reader.
- `tests/test_analytics_files.py`, `tests/test_analytics_store.py` - tracer, negative, fail-closed, confinement, statement-semantics, source-level and Parquet round-trip tests (PG integration gated).
- `tests/fixtures/phase10/loaders/*.json` - `analytics-evidence/1` sample (one candidate experiment with the real trend-pullback baseline-v1 hash, two trades incl. one REJECT, one context, flags, two paper records, universe with matching universe_hash), a `kill-gate-decisions/1` sample, and a universe sample; names and keys avoid the research-gate tripwires.

## Decisions Made

See `key-decisions` above. The most consequential are CANDIDATE-only mapping by parameter-set hash (unknown hashes reported, not guessed) and the fail-closed behaviour when a TESTED_* decision cites experiment ids that are not in the supplied evidence.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical] Family sheet hash normalizes CRLF to LF**
- **Found during:** Task 3 verification (git warned LF to CRLF; `git ls-files --eol` showed the sheets are `i/lf w/crlf` because `core.autocrlf=true` and there is no `.gitattributes`).
- **Issue:** The plan says sha256 of the sheet bytes. On this Windows checkout the working-copy bytes are CRLF, so `sheet_sha256`, and every evidence digest and KILL_GATE_EVALUATION content-hash event id built on it, would differ between this machine and a Linux/CI checkout, breaking the determinism and idempotent-replay guarantees.
- **Fix:** Hash the content after `\r\n` to `\n` normalization (equals the committed blob); slot detection unchanged. Added `test_scan_sheet_hash_is_independent_of_line_endings`.
- **Files modified:** src/adapters/analytics_files.py, tests/test_analytics_files.py
- **Commit:** f9d5e37

**2. [Rule 3 - Blocking] Decision/flag dataclasses defined in Task 1**
- **Issue:** `scan_family_facts(decisions=DecisionsFile, flags_by_experiment=ExperimentFlags)` needs these types in the tracer, while the plan lists the loaders under Task 2.
- **Fix:** Defined `FamilyDecision`, `RecordedTerminal`, `DecisionsFile` and `ExperimentFlags` in the Task 1 GREEN commit; Task 2 added only the loaders and evidence types.
- **Commit:** b42179e

**Total deviations:** 2 auto-fixed (1 missing-critical, 1 blocking ordering). **Impact:** no scope creep; the first strengthens cross-platform determinism.

## Auth Gates

None.

## Issues Encountered

- Bash heredocs containing quote-heavy Python failed to parse in this shell twice; the affected edits were redone with the Edit/Write tools. One mistaken edit (literal newlines inside `b"\r\n"`) broke syntax transiently and was corrected before commit.
- Verification baselines unchanged: mypy reports only the pre-existing `src/adapters/telegram_notify.py:287` error (the analytics typing guard filters to analytics paths and passes); ruff is clean on the four created files.

## Verification

- `pytest tests/test_analytics_files.py tests/test_analytics_store.py tests/test_analytics_typing.py tests/test_analytics_purity.py`: pass (exit 0). Plan verification set also green: `tests/test_domain_mappers.py`, `tests/test_registry.py`, `tests/test_domain_no_float.py`.
- Full repository test suite (`pytest -x`) exits 0.
- `ruff check` on the four created files: clean. `mypy` on both adapters: only the pre-existing telegram_notify error.
- `python scripts/check_migration_parity.py`: exits 0 (no schema change).
- Skipped by design: live-PG test (no `TEST_DATABASE_URL`) and the symlink-escape test (`OSError` creating symlinks on this Windows account).

## Known Stubs

None. Empty/None values are explicit no-data representations (empty universe, empty candle result, NOT_TESTED families) by design.

## Threat Flags

None beyond the plan's register. New file/DB surface (report output paths, journal append) is exactly what T-10-28/29/30/31/32 mitigate: SELECT-only reader, single guarded append, confined output, counted rejects, key-name-only errors, facts-derived independence.

## Next Phase Readiness

Ready for 10-10 to 10-12: the CLI can compose `load_evidence_file` + `scan_family_facts` + `read_journal_events`/`read_live_rows`/`read_candles` into `ReportInputs`, confine the output directory with `confine_output_dir`, and persist the terminal verdict with `append_kill_gate_event`. Open note: a decisions file whose TESTED_* entry names experiment ids absent from the supplied evidence aborts the report (KillGateInputError from FamilyEvidence); the CLI plan should map that to its "Report not produced" copy.

## Self-Check: PASSED

All seven created files exist on disk; all seven task commits (42c858e, b42179e, 9fcb0dc, 39c8b98, 2fa30f8, 3cb6c7f, f9d5e37) exist in `git log`.
