# Lane 4: data_database_concurrency

Stage C (code). Snapshot 63ca176. Lane IDs F-401..F-499. Code is judged against the Stage A/B corrected rules (`lanes/docs_trading_soundness.md` "Corrected Rules for Code Audit", `lanes/docs_exchange_facts.md` "Exchange Facts for Code Audit").

## Scope

- **Persistence layer.** `src/db/models.py`, `src/db/mappers.py`, `src/db/alembic/env.py`, `src/db/alembic/versions/0001..0003`, `alembic.ini`, `.env.example`, `scripts/check_migration_parity.py` and `scripts/dev/migrate.ps1`, compared against `docs/data/DATA_MODEL.md`.
- **Transaction boundaries and approval idempotency.** `src/approval/replay.py`, `src/approval/binding.py`, `src/approval/tokens.py`, `src/approval/mapping.py`, `src/adapters/telegram_callbacks.py`, `src/domain/approval.py`, and `src/execution/manager.py`. From the manager: `execute_approved_plan`, `_place_entry_no_blind_retry`, `attach_protectives_to_fill`.
- **asyncio and shared state.** `src/reconcile/compare.py`, `src/reconcile/sweeper.py`, `src/reconcile/safe_mode.py`, `src/execution/fill_monitor.py`, `src/paper/supervisor.py`, and the `ops/drills.py` journal.
- **asyncio primitives.** I searched all of `src/` for create_task, gather, Lock, to_thread, time.sleep and CancelledError.
- **Data pipeline.** `src/data/store.py`, `src/data/backfill.py`, `src/data/collector.py`, `src/data/quality.py`, `src/data/metadata.py`, the gap logic in `src/data/coverage.py`, `src/sql/coverage_v1.sql`, and `src/adapters/binance_usdm.exchange_info` (projection only).
- **Journal.** `src/domain/journal.py`, `src/paper/journal.py`, `src/adapters/analytics_store.py`, and the journal-id construction in safe_mode, sweeper, telegram_callbacks and drills.
- **Probes.** All probes are in `AUDIT/tmp/data_database_concurrency/`. None connects to a database and none runs Alembic:
  - `probe_enums.py`
  - `probe_backfill_resume.py`
  - `probe_sweeper_resting_entry.py`
  - `probe_tz_rows.py`
  - `probe_numeric_scale.py`
  - `probe_pl_decimal.py`

## Coverage

| file | level | note |
|---|---|---|
| src/db/models.py | DEEP_READ | all 12 tables; metadata inspected in memory |
| src/db/mappers.py | NORMAL_READ | enum/Decimal/datetime round-trip |
| src/db/alembic/env.py | DEEP_READ | |
| src/db/alembic/versions/0001_baseline.py | DEEP_READ | |
| src/db/alembic/versions/0002_domain_registry.py | DEEP_READ | |
| src/db/alembic/versions/0003_callback_mapping.py | DEEP_READ | |
| alembic.ini, .env.example, scripts/dev/migrate.ps1 | NORMAL_READ | |
| scripts/check_migration_parity.py | DEEP_READ | not executed (it runs Alembic offline) |
| docs/data/DATA_MODEL.md | DEEP_READ | |
| src/approval/replay.py | DEEP_READ | |
| src/approval/binding.py | NORMAL_READ | action_to_result, gate |
| src/approval/tokens.py, mapping.py | NORMAL_READ | |
| src/adapters/telegram_callbacks.py | DEEP_READ | |
| src/domain/approval.py, journal.py, canonical.py, enums.py | NORMAL_READ | |
| src/execution/manager.py | NORMAL_READ | L160–600, L802–945 |
| src/execution/fill_monitor.py | NORMAL_READ | fold_fills |
| src/reconcile/compare.py | DEEP_READ | L194–500 |
| src/reconcile/sweeper.py | DEEP_READ | |
| src/reconcile/safe_mode.py | NORMAL_READ | enter/exit/journal |
| src/paper/supervisor.py | DEEP_READ | |
| src/paper/journal.py | DEEP_READ | |
| src/paper/loop.py, resync.py | METADATA_ONLY | outline only |
| src/adapters/paper_ws.py | METADATA_ONLY | outline; F-125 already covers it |
| src/adapters/analytics_store.py | DEEP_READ | |
| src/data/store.py | DEEP_READ | |
| src/data/backfill.py | DEEP_READ | L1–530 |
| src/data/collector.py | DEEP_READ | L1–560 |
| src/data/quality.py | NORMAL_READ | check_batch, klines_to_frame |
| src/data/metadata.py | DEEP_READ | |
| src/data/coverage.py | METADATA_ONLY | grep of the gap logic |
| src/sql/coverage_v1.sql | DEEP_READ | |
| src/core/planner.py, src/core/_decimal.py | NORMAL_READ | _plan_hash, precision |
| src/adapters/binance_usdm.py | NORMAL_READ | L640–780 (exchange_info) |
| src/ops/drills.py | METADATA_ONLY | DrillJournal only |
| tests/test_phase8_audit_reviewfix.py | NORMAL_READ | L230–320 (SKIP tests) |
| tests (create_all users) | METADATA_ONLY | grep |
| .venv psycopg types/datetime.py, _tz.py | NORMAL_READ | how timestamptz values are loaded |
| .venv binance SDK rest_api/models/enums.py | METADATA_ONLY | ContractType enum |

## Verified Safe Areas

- **INV-011 (Decimal for exchange-sensitive values in the database).**
  - Every price, qty, notional, commission and PnL column is `Numeric(38,18)`. No `Float` column exists; the metadata probe confirmed this.
  - The mappers pass `Decimal` through unchanged.
  - The Parquet candle, OI and funding schemas are `pl.Decimal(scale=8/10)`, not float (`quality.py:63-71`, `collector.py:137-148`).
  - Caveat: Polars silently rounds values finer than the column scale (`probe_pl_decimal.py`: 0.123456789 → 0.12345679). This is harmless for live-5 tick sizes of 8 dp or less.
- **INV-015 (UTC timestamps).**
  - All DB timestamp columns are `DateTime(timezone=True)`.
  - The domain dataclasses reject naive and non-UTC values.
  - Partition days use `.date()` on UTC-aware datetimes.
  - See F-406 for the one runtime condition that breaks this.
- **Migration chain.** The chain is linear: 0001 → 0002 → 0003, each `down_revision` is set, there are no branch labels, and every `downgrade()` reverses its `upgrade()` symmetrically. `env.py` refuses to run without `DATABASE_URL`.
- **No `create_all` in src.** The only `create_all` users are in tests. Prod schema authority is Alembic only.
- **INV-096 (fill replay idempotency).**
  - `uq_fills_order_trade (order_id, exchange_trade_id)` exists in both the model and the migration.
  - `fold_fills` dedups by that key.
  - `filled_quantity` sums only the unique fills passed in (`fill_monitor.py:210-269`).
- **Analytics writes.**
  - The only write in the analytics phase is `append_kill_gate_event`. It uses INSERT … ON CONFLICT DO NOTHING on a content-hash PK and refuses any other event type (`analytics_store.py:241-265`).
  - Malformed rows are counted and reported as `InputNote MALFORMED_ROW`, never dropped silently.
- **INV-077 (collector gaps).**
  - A failed poll writes a `collector_gaps` row with a PK-idempotent merge. The reason is truncated to 256 characters.
  - The watermark advances only in the same commit as the snapshot writes.
  - A tick-wide gap uses the `__TICK__` sentinel, never NULL.
- **Collector funding watermark (INV-107).** Resume is per symbol. A FileExistsError on already-written ticks does not wedge the sweep (but see F-408).
- **Backfill cursor (INV-107).**
  - The cursor persists atomically via tmp file + `os.replace`.
  - The forming candle is dropped before the quality gate.
  - Cross-page dedup happens only after the gate passes.
  - A corrupt page rolls the cursor back and is bounded at 5 rejections.
- **Coverage.** The coverage CLI computes a `gap_count` against the interval cadence (`coverage.py:256-277`), so the MIN/MAX-only SQL views do not hide holes.
- **Journal id content hashing (WR-09 fix).** The fix is applied in enablement, health, killgate and `manager._build_cancel_event` via `content_hash_event_id`. It is partial: see F-412.
- **SAFE_MODE exit.** Exit requires a fresh three-source compare and journals SAFE_MODE_EXIT (`safe_mode.py:241-313`). That it is in-memory only is covered by F-127.
- **Blocking I/O.** Every Binance REST call in the adapter runs through `asyncio.to_thread`. The collector's sync DB I/O runs in its own process, with one `asyncio.run` per tick.

## Findings

### F-401 — Orphan sweeper cancels the entry-time stop-loss of a resting, unfilled entry
- **ID:** F-401
- **Severity:** HIGH
- **Confidence:** CONFIRMED (probe)
- **Classification:** DEFECT (root cause includes the doc's orphan definition, INV-094)
- **Category:** concurrency / reconciliation race
- **Component:** src/reconcile/compare.py + src/reconcile/sweeper.py
- **File:** src/reconcile/compare.py
- **Lines:** 293-339 (Pass 1); sweeper.py 184-280
- **Invariant:** INV-094, INV-085, Corrected Rule 14
- **Phase/commit:** Phase 8/9 (compare.py @61d791f)
- **Known-prior:**
  - Related to 09-REVIEW WR-07, which covers the opposite direction: expiry leaves the stop-loss alive.
  - Related to F-952 (cancel-only reconciler never re-places protection).
  - This exact path is not reported anywhere.
- **Evidence:**
  - `execute_approved_plan` places a `closePosition` STOP_MARKET right after the LIMIT entry is acknowledged, before any fill (`manager.py:537-560`).
  - compare Pass 1 treats any protective with no local or exchange position as an orphan: `if is_protective and not has_position: … Divergence(kind=DIVERGENCE_KIND_ORPHAN_PROTECTIVE …)` (compare.py:313-339). It never checks whether an open ENTRY for the same plan or symbol still exists.
  - The sweeper's only guard is "two consecutive zero position reads" (sweeper.py:190-211). That guard is always true while the entry is resting.
  - Probe `probe_sweeper_resting_entry.py` sets up: local ENTRY status NEW, present on the exchange; local SL `xa-…SL` NEW, present on the exchange; no position. Output:
    `divergence: ORPHAN_PROTECTIVE STOP_LOSS xa-…SL`
    `sweeper cancelled: (('BTCUSDT', 'xa-…SL'),)`.
- **Expected:**
  - A protective whose plan's ENTRY is still working (NEW/PARTIALLY_FILLED locally or on the exchange) is not an orphan.
  - Corrected Rule 14 explicitly allows a pre-placed closePosition stop as protection for a resting entry.
- **Actual:** Every reconcile tick while the LIMIT rests (up to the 4 h validity) classifies the pre-fill stop-loss as an orphan and cancels it.
- **Reproduction:**
  ```
  PYTHONPATH=<SNAPSHOT> python -B AUDIT/tmp/data_database_concurrency/probe_sweeper_resting_entry.py
  ```
- **Impact:**
  - The LIMIT then fills with no stop. The next compare flags ENTRY_WITHOUT_PROTECTIVE and enters SAFE_MODE.
  - SAFE_MODE only blocks new entries (`safe_mode.py:214`). It cancels no resting entry and places no stop (F-952), so the position stays unprotected until a human acts.
  - This is a money-loss path as soon as the reconciler and sweeper are composed with live execution.
- **Why tests miss it:** Sweeper tests build orphan diffs by hand. No test runs compare with a working ENTRY plus its pre-placed stop-loss and no position.
- **Remediation:**
  - In compare Pass 1, exempt protectives whose `plan_hash` or symbol has an open local or exchange ENTRY. Classify a protective as an orphan only when its entry is terminal (FILLED-then-flat, CANCELED or EXPIRED).
  - Add the probe scenario as a regression test.
  - Amend INV-094 / RUNBOOK §4 so the orphan definition excludes pre-fill stops.

### F-402 — Backfill publishes a partial UTC day as an "immutable" file; any later run for that day crashes
- **ID:** F-402
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED (probe)
- **Classification:** DEFECT
- **Category:** data pipeline / immutability
- **Component:** src/data/backfill.py + src/data/store.py
- **File:** src/data/backfill.py
- **Lines:** 476-512 (end-of-loop flush), 271-289 (resume); store.py 83-89
- **Invariant:** INV-107, INV-109
- **Phase/commit:** Phase 2 (backfill.py @b468f2a, store.py @8a97eb6)
- **Known-prior:** Not in any prior audit. F-906 and F-122 cover depth and callers, not this.
- **Evidence:**
  - The final flush publishes the latest buffered date even when `end_ms`/now falls mid-day ("every date still in the buffer is now 'as complete as we're going to get'").
  - `publish_batch` raises `FileExistsError` if `part.parquet` exists.
  - Resume starts at `cursor + interval`, which is inside the same day.
  - Probe `probe_backfill_resume.py`:
    - run 1 (now = day 2, 12:00) writes `date=…-02/part.parquet` with 12 rows;
    - run 2 (same day, 20:00, resuming from the cursor) fails with `run2 RAISED FileExistsError refusing to overwrite immutable Parquet at …date=2026-09-02/part.parquet`.
- **Expected:**
  - Either only complete UTC days are published (the current day stays buffered until it closes), or partial days go to versioned partitions or files (`part-<n>.parquet`) plus a manifest.
  - In every case, a scheduled re-run continues without manual deletion.
- **Actual:** Any backfill whose end is not 00:00 UTC leaves a permanently truncated day. Every later run for that symbol/interval aborts on the same day, so data after it can never be ingested without deleting a "published" file.
- **Reproduction:** Run `probe_backfill_resume.py`.
- **Impact:**
  - Research datasets end up with silent truncated days.
  - The incremental backfill path, which the cursor store exists for, is unusable on the same day.
  - The operator's only fix violates D-04 immutability.
- **Why tests miss it:** Tests use frozen clocks aligned to whole days or single runs. None resumes within the day of the last flush.
- **Remediation:**
  - Flush only dates `< floor_day(now)`, and leave the cursor at the last complete day.
  - Or adopt versioned part files with a manifest that supersedes, as DATA_PIPELINE's repair flow already describes.

### F-403 — VARCHAR widths are narrower than real enum and exchange values; the insert fails on PostgreSQL
- **ID:** F-403
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED for the width mismatch; PROBABLE for the runtime trigger
- **Classification:** DEFECT
- **Category:** schema / enum drift
- **Component:** src/db/models.py + 0001/0002 migrations
- **File:** src/db/models.py
- **Lines:** 369 (`positions.status String(16)`), 71 (`symbol_metadata.contract_type String(16)`)
- **Invariant:** INV-025, INV-027
- **Phase/commit:** Phase 2/3 (models.py @3749e08)
- **Known-prior:** none
- **Evidence:**
  - `probe_enums.py` prints `PositionStatus: maxlen=20 (LIQUIDATION_REPORTED)` against `positions status 16`.
  - The installed SDK 17.4.0 `rest_api/models/enums.py:62` defines contract type `TRADIFI_PERPETUAL`, which is 17 characters, against `symbol_metadata contract_type 16`.
  - Binance also emits delivery-state contract types longer than 16 characters (e.g. `PERPETUAL DELIVERING`).
  - `refresh_symbol_metadata(universe=None)` inserts every symbol and commits once (`metadata.py:63-89`).
- **Expected:** Column widths are at least the longest domain enum value and the longest documented exchange value. Better: an unbounded TEXT column, or a CHECK over the enum values.
- **Actual:**
  - PostgreSQL raises `value too long for type character varying(16)`.
  - A LIQUIDATION_REPORTED position row can never be persisted.
  - A full-universe metadata refresh aborts in one transaction once any TradFi perp is listed.
- **Reproduction:** `python -B probe_enums.py` compares enum lengths with column lengths.
- **Impact:** Persistence fails exactly at a liquidation, which is an audit and journal hole. The metadata refresh fails, so constraint snapshots go stale.
- **Why tests miss it:**
  - Tests run on SQLite, which ignores VARCHAR length. The PG mapper tests are skipped (`tool-output/pytest.txt:38-42`).
  - The exchangeInfo fixture holds only 5 PERPETUAL symbols.
- **Remediation:**
  - Widen `positions.status` and `contract_type` (or use TEXT) via a new migration.
  - Add a unit test that asserts `max(len(enum.value)) <= column.length` for every enum-backed column.
  - Pass `universe=LIVE_5` in the refresh caller.

### F-404 — The schema carries none of the DATA_MODEL §5 integrity guards; idempotency and replay-safety exist only as in-process locks and injected, unimplemented stores
- **ID:** F-404
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED (schema read plus in-memory metadata probe)
- **Classification:** GAP
- **Category:** schema constraints / transaction boundaries
- **Component:** src/db/models.py, migrations 0002/0003, src/approval/replay.py, src/adapters/telegram_callbacks.py
- **File:** src/db/models.py
- **Lines:** 176-398; replay.py 48-66, 188-237; telegram_callbacks.py 205-216, 391-424
- **Invariant:** INV-027, INV-029, INV-046, INV-096, Corrected Rule 28
- **Phase/commit:** Phase 3/8
- **Known-prior:**
  - F-126 (approval consumption not implemented).
  - F-956 (runtime composition M1–M4).
  - F-127 (in-memory SAFE_MODE).
  - F-112 (missing Trade and other entities).
  - This finding is the schema and transaction facet of those; the constraints below are not reported elsewhere.
- **Evidence:**
  - `probe_enums.py`: every table reports `FK: 0`. The only unique constraint in the metadata is `uq_fills_order_trade`. There are no CHECK constraints.
  - DATA_MODEL §5: "Foreign keys must prevent orphan domain rows …; Unique constraints must protect deterministic IDs and exchange event replay; Audit/journal events are append-only."
  - The following are missing:
    - (a) a unique constraint on `approvals.approval_token_hash`, which is the idempotency key `resolve_callback` looks up (`replay.py:160`);
    - (b) a guard allowing at most one decided (APPROVED/SKIPPED) approval per `trade_plan_id`;
    - (c) a unique constraint on `orders.client_order_id` / `algo_client_id` (Corrected Rule 28 needs durable local dedup);
    - (d) a unique constraint on `trade_plans.signal_id` ("zero or one active trade plan");
    - (e) any append-only enforcement on `journal_events` (no trigger or REVOKE UPDATE/DELETE). `created_at_utc` is nullable with no server default.
  - `replay.py:48-53` itself states: "Cross-process races still need a conditional write (UPDATE … WHERE status='PENDING') at the store layer." It serializes only with a process-local `threading.Lock` held in an unbounded `_TOKEN_LOCKS` dict. The lock is held while the sync `save` runs, which puts sync DB I/O on the PTB event loop.
  - No src module writes approvals, orders, fills, positions, signals, trade_plans or journal rows, apart from the KILL_GATE append.
- **Expected:**
  - Idempotency and at-least-once replay safety are enforced by the database: unique keys, a conditional PENDING→decided UPDATE, and FKs.
  - Approval transition, short-id mapping and order intent are persisted in one transaction.
- **Actual:** Every guarantee depends on callables injected by a runtime that does not exist, and the schema would not stop a buggy or concurrent writer.
- **Reproduction:** `python -B probe_enums.py`, section "constraints/indexes/FKs".
- **Impact:** When the runtime is composed (P11+ / M1–M4), two processes or a restart can:
  - decide one plan twice,
  - store duplicate order intents for one client id, or
  - rewrite the journal,
  with no DB error. This is the durable dedup Corrected Rule 28 requires to stop re-submission after a fill or cancel.
- **Why tests miss it:** The tests inject in-memory fakes (`_Store`, lambdas). The PG tests use `create_all` and are skipped.
- **Remediation:**
  - Add migration 0004 with:
    - FKs, with the `NULL` lifecycle exceptions documented;
    - `UNIQUE(approval_token_hash)`;
    - a partial unique `(trade_plan_id) WHERE status IN ('APPROVED','SKIPPED')`;
    - `UNIQUE(client_order_id)` and `UNIQUE(algo_client_id)` WHERE NOT NULL;
    - `UNIQUE(signal_id)` on `trade_plans`;
    - a journal UPDATE/DELETE-blocking trigger.
  - Implement the approval store as one transaction using `UPDATE … WHERE status='PENDING' RETURNING`, with a 0-row result mapped to replay-return-existing.
  - Make the store async so it does not block the loop.

### F-405 — The SKIP button can never succeed: APPROVE and SKIP share one short id, one token and one approval row with a single stored action
- **ID:** F-405
- **Severity:** MEDIUM
- **Confidence:** PROBABLE (code path traced; the runtime resolver is not implemented)
- **Classification:** DEFECT
- **Category:** approval data model
- **Component:** src/adapters/telegram_callbacks.py, src/approval/replay.py, src/domain/approval.py
- **File:** src/approval/replay.py
- **Lines:** 215-219; telegram_callbacks.py 674-687; domain/approval.py 44-50
- **Invariant:** INV-023, INV-046, INV-048, D-03 opportunity attribution
- **Phase/commit:** Phase 8 (CR-01 fix)
- **Known-prior:** F-961 covers the inert SIMULATE buttons, not this.
- **Evidence:**
  - `on_callback` resolves the binding and the raw token by `parsed.short_id` only: `binding = binding_context_resolver(parsed.short_id); raw_token = binding.get("raw_token", "")`.
  - The APR and SKP keyboards carry the same short id: `tests/test_approval_message.py:189 assert apr_cb[len("APR:"):] == skp_cb[len("SKP:"):]`.
  - So both buttons reach the same approval row. That row stores one `action` before any press.
  - `replay.py:215`: `if callback.action is not None and callback.action != approval.action: raise ApprovalRejected(... "callback action != approval action")`.
  - `tests/test_phase8_audit_reviewfix.py:245-262` pins that a SKIP press on an APPROVE row is INVALIDATED and the row stays PENDING.
- **Expected:**
  - The row is PENDING with no chosen action, and the pressed button decides APPROVED or SKIPPED.
  - Or there are two rows or tokens per plan, plus a DB guard that only one gets decided (see F-404 b).
- **Actual:** For a normal approval request (row action = APPROVE), pressing SKIP always renders "Rejected (INVALIDATED)". The skip is never recorded, and the plan stays PENDING until expiry.
- **Reproduction:** Trace `on_callback` → `dispatch_callback` → `resolve_callback` with `ParsedCallback(kind=SKIP)` against a pending APPROVE row. The existing test `test_cr01_replay_skip_button_on_approve_plan_fails_closed` demonstrates the outcome.
- **Impact:**
  - User SKIP decisions and skip reasons are lost, so opportunity and user-attribution analytics (D-03) and approval-delay evidence are wrong.
  - The operator gets a confusing rejection.
  - This does not lead to money loss directly.
- **Why tests miss it:** The tests treat "action pre-stored on the row" as correct and never compose short-id → token resolution with both buttons.
- **Remediation:**
  - Store PENDING rows without a decided action, and let `action_to_result(callback.action)` decide.
  - Keep CR-01's intent: the pressed button decides, and a SIMULATE press never transitions the row.
  - Enforce single decision with the conditional UPDATE from F-404.

### F-406 — Reads from a PostgreSQL whose TimeZone is not UTC make every mapper reject every row
- **ID:** F-406
- **Severity:** MEDIUM
- **Confidence:** PROBABLE (psycopg behaviour confirmed from its installed source; mapper failure confirmed by probe)
- **Classification:** DEFECT
- **Category:** timezone / DB boundary
- **Component:** src/db/models.py make_engine; src/domain/* validators; src/adapters/analytics_store.py
- **File:** src/db/models.py
- **Lines:** 439-457
- **Invariant:** INV-015
- **Phase/commit:** Phase 3/10
- **Known-prior:** none
- **Evidence:**
  - psycopg `TimestamptzLoader` builds datetimes in `get_tzinfo(pgconn)`, the session `TimeZone` (`.venv/…/psycopg/types/datetime.py:486`, `_tz.py:23-31`).
  - `make_engine` passes no `options=-c timezone=UTC` and no connect hook.
  - The domain validators require `utcoffset()==0`.
  - Probe `probe_tz_rows.py`, on an instant loaded as Asia/Ho_Chi_Minh: `journal_from_row RAISED ValueError occurred_at_utc must be UTC, got offset 7:00:00`, and `journal_rows_to_events -> ((), 1)`.
- **Expected:** The engine pins the session TimeZone to UTC, or the mappers normalise aware datetimes with `astimezone(UTC)` at the boundary.
- **Actual:**
  - On any PG whose `TimeZone` is not UTC, every Signal, Plan, Approval, Order, Fill, Position and Journal row fails conversion.
  - An example is a native Windows install on a Vietnam host, where the installer takes the OS zone.
  - Analytics reports them all as MALFORMED_ROW, so the evidence set is empty.
- **Reproduction:** `python -B probe_tz_rows.py`.
- **Impact:**
  - The kill-gate and paper evidence read as empty or incomplete.
  - Any future runtime that reloads state fails on every row. It fails closed, but it is unusable.
  - The Compose `postgres:17` image defaults to UTC, which masks this.
- **Why tests miss it:** SQLite drops tzinfo, and the PG tests are skipped.
- **Remediation:**
  - Use `create_async_engine(url, connect_args={"options": "-c timezone=UTC"})` and the same in Alembic `env.py`.
  - Alternatively, normalise with `astimezone(UTC)` in the mappers.
  - Add a PG test with a non-UTC session.

### F-407 — Portfolio and cluster caps are not serialized across concurrent approvals (no lock anywhere)
- **ID:** F-407
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED (structural)
- **Classification:** GAP
- **Category:** asyncio concurrency / TOCTOU
- **Component:** src/execution/manager.py execute_approved_plan
- **File:** src/execution/manager.py
- **Lines:** 418-450, 497-520
- **Invariant:** INV-063, INV-064, INV-065, Corrected Rule 9
- **Phase/commit:** Phase 9 (manager.py @d029a21)
- **Known-prior:**
  - F-908 (caps count filled positions only).
  - F-955 (the roadmap omits "caps under a lock").
  - This finding is the code-level confirmation.
- **Evidence:**
  - `evaluate_risk(**risk_kwargs)` and `decide_placement(reconciled_positions=risk_kwargs["open_positions"], …)` judge a caller-supplied position snapshot.
  - The coroutine then yields at `await adapter.get_position_mode()` and `await adapter.place_entry`.
  - `src/` contains no `asyncio.Lock` or other serialization. The only locks are `threading.Lock`s in `replay.py` and `ops/drills.py`.
  - Two APPROVE callbacks handled concurrently (PTB runs handlers concurrently when `concurrent_updates` is set; separate processes always run concurrently) both see the same snapshot and both pass.
- **Expected:** One serialized section, covering cap check, reservation of the plan's risk (working and approved-but-unplaced) and placement, both at approval and at placement (Corrected Rule 9).
- **Actual:** No reservation and no lock exist, so aggregate and cluster risk can be exceeded by N concurrent approvals.
- **Reproduction:** Code reading. Two `execute_approved_plan` tasks with the same `open_positions=[]` both reach `place_entry`.
- **Impact:** Aggregate or cluster risk above the configured cap (1% / 0.5%). The impact is latent until a runtime exists.
- **Why tests miss it:** The tests call `execute_approved_plan` sequentially with fixtures.
- **Remediation:**
  - Add a process-wide `asyncio.Lock`, or a PG advisory lock for multiple processes.
  - Inside it: recompute open risk, including working entries and APPROVED-unplaced plans; persist a reservation row; place the entry.
  - Release the reservation when the entry is terminal.

### F-408 — Parquet data files are written non-atomically; a torn file becomes permanent "immutable" data
- **ID:** F-408
- **Severity:** LOW
- **Confidence:** PROBABLE
- **Classification:** DEFECT
- **Category:** data pipeline durability
- **Component:** src/data/store.py, src/data/collector.py
- **File:** src/data/store.py
- **Lines:** 83-89; collector.py 170-181, 209, 239, 269, 509-525
- **Invariant:** INV-107
- **Phase/commit:** Phase 2
- **Known-prior:** none
- **Evidence:**
  - `path.exists()` check, then `group_to_write.write_parquet(path)` straight to the final path, with no tmp file and no `os.replace`.
  - The cursor store does use tmp + replace (`backfill.py:169-176`), so the pattern is known.
  - The funding sweep treats `FileExistsError` as "the tick IS on disk, so it is covered" (`collector.py:514-525`).
- **Expected:** Write to `*.tmp`, fsync, then `os.replace` (or `os.link` for no-clobber). Only a complete file counts as published.
- **Actual:**
  - A crash or disk-full mid-write leaves a truncated `part.parquet` or tick file.
  - Later runs refuse to overwrite it (backfill aborts; funding counts it as covered and advances the watermark).
  - `read_candles` counts the file only as "unreadable partition".
- **Reproduction:** Code reading.
- **Impact:** Permanent data holes that look published.
- **Why tests miss it:** There is no crash-injection test.
- **Remediation:** Use atomic publish (tmp + `os.replace`). On FileExistsError, validate the existing file (readable, and its row count or hash matches the manifest) before treating it as covered.

### F-409 — The quality gate treats zero-trade klines as structurally corrupt and can permanently halt a backfill
- **ID:** F-409
- **Severity:** LOW
- **Confidence:** PROBABLE
- **Classification:** DEFECT
- **Category:** data quality
- **Component:** src/data/quality.py
- **File:** src/data/quality.py
- **Lines:** 170-203
- **Invariant:** INV-108
- **Phase/commit:** Phase 2
- **Known-prior:** none
- **Evidence:**
  - `negative_values = sum(1 for k in klines if … or k.trade_count <= 0)`, and then `structural_ok = … and negative_values == 0`.
  - `backfill.py:437-450` rolls the cursor back and raises `StructuralRejectionError` after 5 consecutive rejections.
- **Expected:** A kline with 0 trades (volume 0, OHLC = previous close) is a valid exchange observation. It should be flagged, not rejected. Only negative values should be structural.
- **Actual:** One zero-trade bar in a 1000-bar page rejects the whole page, and backfill for that symbol/interval stops at that point on every run.
- **Reproduction:** Code reading. The trigger is Binance returning a zero-trade kline, which happens on illiquid 1m bars and in maintenance windows.
- **Impact:** A data hole at research-universe expansion (F-907), rare for the live-5.
- **Why tests miss it:** The fixtures always have `trade_count >= 1`.
- **Remediation:** Change the check to `trade_count < 0`. Record zero-trade bars as a warn-only flag in the verdict.

### F-410 — NUMERIC(38,18) rounds and scale-pads the pure core's precision-28 Decimals; persisted plans cannot reproduce `plan_hash`
- **ID:** F-410
- **Severity:** LOW
- **Confidence:** CONFIRMED (probe of the arithmetic; the PG rounding is standard NUMERIC semantics)
- **Classification:** DEFECT
- **Category:** Decimal precision / reproducibility
- **Component:** src/db/models.py TradePlanRow; src/core/planner.py _plan_hash
- **File:** src/db/models.py
- **Lines:** 223-234; planner.py 52-78; core/_decimal.py 19
- **Invariant:** INV-011, INV-013 (determinism and reproducibility)
- **Phase/commit:** Phase 3/4
- **Known-prior:** none
- **Evidence:**
  - `probe_numeric_scale.py`: `entry_max 0.5129107142857142857142857143 frac digits 28`, and `hash(in-memory) == hash(as NUMERIC(38,18) returns it)? False`.
  - Even exact values are padded: `0.5 → 0.500000000000000000`. `canonical_scalars` hashes `str(Decimal)`, which is scale-sensitive by design.
- **Expected:**
  - Plan prices are tick-quantized (Corrected Rule 6) before hashing and persistence, so the stored value equals the hashed value.
  - Mappers normalise the scale on load.
- **Actual:** Unquantized precision-28 values are hashed. A DB round-trip changes both digits and scale, so `plan_hash` cannot be re-verified from the persisted row.
- **Reproduction:** `python -B probe_numeric_scale.py`.
- **Impact:** Audit and replay verification fail on the canonical store. There is no order impact today, because placement re-quantizes from in-memory values.
- **Why tests miss it:** The mapper round-trip uses Decimal equality, which ignores scale, and runs on SQLite.
- **Remediation:**
  - Quantize the plan prices to tickSize in the planner.
  - Or hash a normalised form, e.g. `format(d.normalize(), 'f')`, and normalise in `*_from_row`.

### F-411 — The ORM metadata omits every index and the only unique index of the migrations; the parity check and tests cannot see it
- **ID:** F-411
- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Classification:** DRIFT
- **Category:** migrations
- **Component:** src/db/models.py vs versions/0001-0003; scripts/check_migration_parity.py
- **File:** src/db/alembic/versions/0003_callback_mapping.py
- **Lines:** 33-38 (the `uq_short_id_mapping_signal_trade_plan` unique index); models.py 404-428; check_migration_parity.py 118-121, 193-210
- **Invariant:** INV-027
- **Phase/commit:** Phase 2/3/8
- **Known-prior:** none
- **Evidence:**
  - `probe_enums.py` shows `idx: []` for every table in `Base.metadata`.
  - The migrations create 14 indexes, including the unique `(signal_id, trade_plan_id)` guard that the 0003 docstring presents as a fail-closed rebinding guard.
  - The parity script skips `CONSTRAINT|FOREIGN KEY|UNIQUE|CHECK` lines and compares columns and PK only.
  - The PG tests build their schema with `create_all` (tests/test_domain_mappers_pg.py, test_analytics_store.py), so migrations are never executed by any test, and all PG tests are skipped.
- **Expected:** `models.py` is the declared "single source of schema truth", so it declares the same Index and UniqueConstraint objects, and the parity check compares indexes and constraints.
- **Actual:**
  - `alembic revision --autogenerate` would propose dropping all 14 indexes.
  - Tests run without the unique short-id guard.
  - A migration typo in an index would pass "parity green".
- **Reproduction:** Run `python -B probe_enums.py`. Compare with `op.create_index` in the migrations.
- **Impact:** Schema drift risk, and guards that are claimed but never tested.
- **Why tests miss it:** See Evidence.
- **Remediation:**
  - Declare `Index(...)` / `UniqueConstraint` in the models.
  - Extend the parity script to compare `inspect`-style index and constraint sets.
  - Build the PG test schema by running migrations, not `create_all`.

### F-412 — The WR-09 journal-id fix is incomplete: SAFE_MODE, sweeper, drill and callback events still use (name, millisecond) primary keys
- **ID:** F-412
- **Severity:** LOW
- **Confidence:** PROBABLE
- **Classification:** DEFECT
- **Category:** journal replay-safety
- **Component:** src/reconcile/safe_mode.py, src/reconcile/sweeper.py, src/ops/drills.py, src/adapters/telegram_callbacks.py
- **File:** src/reconcile/safe_mode.py
- **Lines:** 327; sweeper.py 320-323, 349-352, 377-380; drills.py 402; telegram_callbacks.py 586
- **Invariant:** INV-029, INV-048
- **Phase/commit:** Phase 8/9
- **Known-prior:** KNOWN:09-REVIEW WR-09, which was fixed only for health, enablement, killgate and the manager cancel event.
- **Evidence:**
  - `journal_event_id=f"safe_mode_{event_type.lower()}_{int(now_utc.timestamp() * 1000)}"`.
  - `enter_safe_mode` journals SAFE_MODE_REENTER each time the reason changes. With one injected `now_utc` per reconcile tick, two reason changes in a tick produce the same PK.
  - `cb-outcome:` ids add `uuid4` (non-deterministic, so not replay-safe in the other direction).
- **Expected:** `content_hash_event_id(...)` everywhere, as `domain/journal.py:20` prescribes.
- **Actual:** A PK collision produces an IntegrityError, or the event is silently dropped under upsert or ON CONFLICT DO NOTHING. The audit trail loses a SAFE_MODE transition.
- **Reproduction:** Call `enter_safe_mode(reason="A", now_utc=t)`, then `(reason="B", t)`, then `(reason="C", t)`. The second and third REENTER ids are identical.
- **Impact:** Audit gaps in SAFE_MODE history.
- **Why tests miss it:** The in-memory DrillJournal appends to a list and never enforces PK uniqueness.
- **Remediation:** Route every event id through `content_hash_event_id`. Enforce PK uniqueness in the fake journal used by tests.

### F-413 — The paper supervisor resubscribes before backfilling: live closes can overtake and duplicate backfilled closes
- **ID:** F-413
- **Severity:** LOW
- **Confidence:** PROBABLE
- **Classification:** DEFECT
- **Category:** asyncio ordering
- **Component:** src/paper/supervisor.py
- **File:** src/paper/supervisor.py
- **Lines:** 230-315, 155-167
- **Invariant:** INV-095, INV-003 (closed-candle ordering)
- **Phase/commit:** Phase 7
- **Known-prior:** F-125 (the paper WS adapter is broken, so this is latent)
- **Evidence:**
  - `_resubscribe_and_backfill` calls `self._close_all_handles(); self.start()` first, then `await backfill_missed_closes(... now_utc=now)` per pair.
  - The WS handler dispatches closed klines immediately (`_on_kline` → `self._on_closed_candle`) while the backfill is awaited.
  - The backfilled closes are only returned to the caller afterwards, and span up to `now`. Any candle that closes during the await is therefore both dispatched live and included in the backfill, and it reaches the loop before the older missed closes.
  - Backfilled closes also do not advance `_last_close`, so a second disconnect before a fresh WS close re-backfills and re-dispatches the same range.
- **Expected:** INV-095: "no approval or placement during the resync window". That means buffering WS closes during resync, dispatching backfilled closes in order, deduping by (symbol, interval, open_time), and then draining the buffer.
- **Actual:** Candles can be dispatched out of order and duplicated after every reconnect, including the 24 h rotation.
- **Reproduction:** Code reading.
- **Impact:** Paper evaluation may diverge from backtest determinism (duplicate or out-of-order signals), and paper parity evidence is corrupted.
- **Why tests miss it:** The tests use synchronous fakes with no interleaving.
- **Remediation:** Gate the WS dispatch with a resync flag and buffer. Dedup and sort by open_time. Call `record_close` for backfilled closes.

## Open Questions

- **Approval token (L7 lane).** `on_callback` gets `raw_token` from the server-side `binding_context_resolver(short_id)`, because the callback_data carries only the short id. The "one-time token proves the human pressed the button" check is therefore a comparison of the server with itself. The raw token also has to be stored server-side, which contradicts "raw token never persisted" (`tokens.py` docstring) unless it lives only in memory, in which case it is lost on restart. Please confirm the intended token transport.
- **exchangeInfo drift (L5 lane).** `binance_usdm.exchange_info` aborts the whole refresh when any symbol lacks PRICE_FILTER, LOT_SIZE or MIN_NOTIONAL (`drifted` → ValueError, L770-774). One delisting or exotic symbol anywhere on the exchange blocks metadata for the live-5. The adapter should filter to the universe before validating.
- **Short-id mapping (for F-404/F-405).** `dispatch_callback` requires the mapping row to exist (`lookup_by_short_id`) and then passes a freshly built `new_mapping` to `save_atomic` "on the first transition". If the row already exists, inserting it again violates the `short_id` PK. The contract ("the callable decides whether to insert") is unclear, and no implementation exists.
- **Retention purge.** The 0003 docstring promises a "scheduled purge" of `short_id_mapping`. No code implements it.
- **Candle storage.** AMB-038 / DATA_MODEL §2.1 describe `market_candles` in PostgreSQL. The code stores candles only in Parquet (D-05). I did not raise this: it is a documented decision, and the planning lanes judge it.
- **Out of reach.** I could not run `scripts/check_migration_parity.py` because it runs Alembic offline, which this lane is not allowed to do. The index and unique conclusions in F-411 come from reading the source plus the metadata probe.
