---
base: 85392f439a7030b718395301332bd60a6f6e601b
phase: 18-user-data-stream-error-taxonomy
plan: 08
subsystem: domain/stream-records, persistence/entities
status: complete
tags: [persistence, journal, unknown-exit, evidence, G4-034, G4-043, D-05, D-08, D051, EXEC-02, EXEC-05]
requires: [18-03]
provides:
  - src/domain/stream_records.py (EvidenceSource, ExitEvidence, exit_evidence_event, stream_anomaly_event, UNKNOWN_EXIT_EVIDENCE, STREAM_ANOMALY, USER_DATA_STREAM)
  - src/persistence/errors.py (EvidenceRequired)
  - src/persistence/entities.py (PgTradingEntityStore(db, *, journal=None); transition_order / transition_position keyword evidence; update_order_exchange_state; get_order_by_client_order_id; get_order_by_algo_client_id)
  - src/persistence/__init__.py (complete module map, tested)
affects:
  - plan 18-15 (the stream router is the first caller of the evidence gate, the exchange-state writer, the two lookups and stream_anomaly_event)
  - Phases 20 and 24 (wiring into a running process; REST reconcile supplies EvidenceSource.REST_RECONCILE)
tech-stack:
  added: []
  patterns:
    - UNKNOWN exit gate inside the existing lock / no-op / assert / conditional-UPDATE sequence, journal append in the same unit of work
    - deterministic journal ids through correlated_event_id keyed on (correlation, entity, step)
    - pure record builders with injected time and sorted-key compact ASCII JSON of text values only
key-files:
  created:
    - src/domain/stream_records.py
    - tests/test_stream_records.py
    - tests/test_persistence_exit_evidence_pg.py
  modified:
    - src/persistence/entities.py
    - src/persistence/errors.py
    - src/persistence/__init__.py
decisions:
  - "The exit-evidence id step is \"<from>-><to>\" (as planned), so the same exit recorded again with a different source or reference is a JournalConflict that rolls the status change back, never a silent second row"
  - "ExitEvidence.detail is validated (None or 1 to 200 characters) but not journaled, because the plan fixes the payload to exactly five keys"
  - "ExitEvidence.reference and correlation_id are capped at 128 characters (journal column width); reference must be printable ASCII without whitespace and refuses the words listenkey, apikey, api_key, secret, signature and password (case-insensitive), so a credential cannot reach the payload through it"
  - "exit_evidence_event refuses an entity type other than ORDER or POSITION, a from_status other than UNKNOWN, and a to_status of UNKNOWN"
  - "The evidence gate also raises TypeError when evidence is not an ExitEvidence"
  - "update_order_exchange_state writes through the existing _apply conditional UPDATE keyed on the unchanged local_status, so it cannot race a concurrent local transition; it also refuses a naive or non-UTC now_utc and an exchange_order_id that is empty or longer than 64 characters"
  - "The two lookups refuse an empty or non-string key with ValueError; an unknown key returns None"
metrics:
  duration: 35min
  completed: 2026-10-16
estimate:
  tokens: 70000
  tasks: 2
actuals:
  tokens: 13800
  tasks: 2
  commits: 6
plan_head_before: 85392f439a7030b718395301332bd60a6f6e601b
plan_head_after: 77df17c83d1d745ca0ac52a59b47d4434536daa0
---

# Phase 18 Plan 08: Evidence-Gated UNKNOWN Exits, Order Exchange State and Stream-Anomaly Records Summary

An Order or a Position now leaves UNKNOWN only with an `ExitEvidence` (REST reconcile or user-data event). The UNKNOWN_EXIT_EVIDENCE journal event is appended in the same PostgreSQL transaction as the status change, and `EvidenceRequired` is raised with nothing written when the evidence or the journal is missing. The Order's `exchange_status` and `exchange_order_id` have a writer that also works on terminal orders, and there are lookups by client order id and by algo client id. `stream_anomaly_event` gives each duplicate frame in a session one deterministic journal record. No table, migration or package was added.

## Performance

- Duration: about 35 minutes
- Tasks: 2 of 2
- Files: 3 created, 3 modified

## Task Commits

1. Task 1 (tracer): an Order leaves UNKNOWN only with Binance evidence journaled in the same transaction: `231c996`
2. Task 2: Position evidence gate, stream-anomaly journal event, Order exchange-state writer, client-id lookups and module map: `77df17c`

The measured range `85392f4..77df17c` holds 6 commits because the concurrent plan 18-09 committed `a55638d`, `88ae30c`, `eb0c0cf` and `ba93e15` on the same branch. Plan 18-08 made 2 task commits.

## What Was Built

- `src/domain/stream_records.py` (pure: stdlib plus `src.domain.journal`):
  - `EvidenceSource`: REST_RECONCILE or USER_DATA_EVENT.
  - `ExitEvidence`: frozen and validated.
  - `exit_evidence_event`: id `correlated_event_id(prefix="ev", ..., step="<from>-><to>")`. The payload is sorted-key compact JSON with exactly the keys evidence_source, from_status, observed_at_utc, reference and to_status. The order_id or position_id link is set.
  - `stream_anomaly_event`: event type STREAM_ANOMALY, entity type USER_DATA_STREAM, entity id `"<kind>:<payload_sha256>"`, correlation id = session id. The id is `correlated_event_id(prefix="sa", ..., step=payload_sha256)`. The payload has exactly kind, event_name, field, detail, payload_sha256 and observed_at_utc. `kind` is plain text, and every `StreamAnomalyKind` value is accepted (tested).
- `src/persistence/errors.py`: `EvidenceRequired(PersistenceError)`.
- `src/persistence/entities.py`:
  - `PgTradingEntityStore(db, *, journal=None)`.
  - `transition_order` and `transition_position` take the keyword `evidence`. The checks run after the idempotent no-op and before `assert_transition`: leaving UNKNOWN needs evidence and a journal, and evidence for any other move raises ValueError. After the conditional UPDATE, the event is appended through `PgJournalStore.append(session, event)` in the same unit of work. The `tx` join semantics are unchanged.
  - `update_order_exchange_state(order_id, *, exchange_status, exchange_order_id=None, now_utc, tx=None)` locks the row. It sets `exchange_status` and `updated_at_utc`, and sets `exchange_order_id` only when none is stored (None keeps the stored id). A different stored id raises `RowConflict`. An unchanged state is a no-op, and `local_status` is never touched.
  - `get_order_by_client_order_id` and `get_order_by_algo_client_id` both accept `tx`.
- `src/persistence/__init__.py`: the module map lists all 11 modules. The "no re-exports" rule and the D-02 paragraph are kept.

Migration 0004 was read before the exchange-state test. `reject_terminal_status_change('local_status', 'FILLED', 'CANCELED', ...)` compares only `TG_ARGV[0]` (`local_status`), so `exchange_status` writes on terminal orders are allowed. The PG tests confirm this for FILLED, CANCELED, EXPIRED and REJECTED. A raw `UPDATE orders SET local_status = 'NEW'` on a FILLED or CANCELED order still fails with the P0001 "terminal" error, and `transition_order` still raises `IllegalTransition`.

## Verification

All runs used TEST_DATABASE_URL set inline. The PostgreSQL work ran on generated `t17_*` databases only.

- Task 1 verify: `pytest -m "not docker" tests/test_stream_records.py tests/test_persistence_exit_evidence_pg.py tests/test_persistence_transitions_pg.py -x -rs` gave 105 passed, 0 skipped.
- Task 2 / plan verify: `pytest -m "not docker" tests/test_stream_records.py tests/test_persistence_exit_evidence_pg.py tests/test_persistence_transitions_pg.py tests/test_persistence_journal_pg.py -x -rs` gave 167 passed, 0 skipped. By file: 50 in test_stream_records.py (pure); 31 in test_persistence_exit_evidence_pg.py (30 PostgreSQL, 1 module-map test that needs no database); 65 in test_persistence_transitions_pg.py (Phase 17, unchanged and passing); 21 in test_persistence_journal_pg.py.
- Without TEST_DATABASE_URL, the PostgreSQL tests of the new file skip loudly (checked once).
- `mypy src`: no issues in 193 source files. `ruff check`: all checks passed. `ruff format --check`: 572 files already formatted. `uv lock --check`: resolved.
- `git diff --stat 85392f4..HEAD -- src/persistence/execution_state.py src/db/alembic` prints nothing.

## Deviations from Plan

1. **[Format] `base:` is the first frontmatter key, not the literal first line.** The output spec asks for `base: <sha>` as the first line. Putting it before the `---` frontmatter would break the frontmatter that the audit scanner reads (`status: complete`). It is therefore line 2, the first key, and `grep '^base:'` still finds it.
2. **[Rule 2 - Security] Reference hygiene on ExitEvidence.** The truth "payloads never contain a listenKey or a credential" can only hold if the free-text `reference` is constrained. It is restricted to printable ASCII without whitespace, at most 128 characters, and refuses credential-shaped words. `correlation_id` is capped at the 128-character journal column. Tested in `tests/test_stream_records.py`.
3. **[Rule 2 - Correctness] Extra input validation.** Not in the plan's behavior list, but all fail closed with ValueError or TypeError before any write:
   - `exit_evidence_event` restricts the entity type to ORDER or POSITION and requires from_status UNKNOWN.
   - `update_order_exchange_state` refuses a non-UTC `now_utc` and an empty or over-64-character `exchange_order_id` (column width).
   - The lookups refuse an empty key.
   - The gate raises TypeError on a non-ExitEvidence `evidence`.

No other deviation. No package was installed, and no table or migration was added.

## Known Stubs

None.

## Open Items

- The other Phase 17 review info items in `src/persistence/execution_state.py` remain open for Phase 20, as the plan scoped.
- Nothing calls these methods in a running process yet. Plan 18-15 (router) is the first caller; process wiring is Phases 20 and 24.
- Concurrent-executor note: during Task 1, `ruff check` over the whole tree reported one E501 in `src/adapters/binance_client.py`. That was uncommitted work of the concurrent plan 18-09 and was not touched. The final whole-tree `ruff check` passed.

## Self-Check: PASSED

- FOUND: src/domain/stream_records.py, tests/test_stream_records.py, tests/test_persistence_exit_evidence_pg.py
- FOUND commits: 231c996, 77df17c
