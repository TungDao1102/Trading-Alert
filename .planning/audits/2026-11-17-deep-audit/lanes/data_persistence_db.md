# Lane M11: data_persistence_db

## Scope
`src/data/*`, `src/persistence/*` (except files owned by M03/M04/M05: `pending_actions.py`,
`risk_reservations.py`, `day_risk.py`, `safe_mode_store.py`, `system_state.py`), `src/db/**`,
`src/adapters/analytics_*.py`, `alembic.ini`. Snapshot `55885b9`. Findings G-1100..1199.
No database connection was made (charter rule); PostgreSQL behaviour is reasoned from the
SQL/DDL text, not observed.

## Coverage
| File | Level | Note |
|---|---|---|
| `src/persistence/engine.py` | DEEP_READ | timeouts, UTC pin, fail closed |
| `src/persistence/uow.py` | DEEP_READ | error translation; default isolation READ COMMITTED |
| `src/persistence/execution_state.py` | DEEP_READ | consume + intent atomicity |
| `src/persistence/entities.py` | DEEP_READ | state machines, precision guard, event-time guard |
| `src/persistence/approvals.py` | DEEP_READ | single decision; EXPIRED sibling race reasoned |
| `src/persistence/journal.py` | DEEP_READ | append-only, replay compare |
| `src/db/models.py` | DEEP_READ | all tables |
| `src/db/alembic/env.py`, `alembic.ini` | DEEP_READ | URL from env only |
| `src/adapters/analytics_store.py` | DEEP_READ | read-only + one guarded append |
| `src/live/stream_persistence.py` (caller, not my scope) | NORMAL_READ | only to find who writes orders / fills / positions |
| `src/db/alembic/versions/0001..0015` | NORMAL_READ + probe | rendered offline to SQL (`probe_ddl.py`, no connection); 0004 triggers, 0014, 0015 read in full; others compared by probe |
| `src/db/mappers.py` | NORMAL_READ | total field mapping; enum restore raises on unknown |
| `src/persistence/snapshots.py` | DEEP_READ | write-once, digest verified on read |
| `src/persistence/lot_filters.py` | DEEP_READ | monotonic upsert |
| `src/persistence/errors.py` | DEEP_READ | |
| `src/persistence/paper_runtime_state.py` | NORMAL_READ | journal-only state, advisory-lock lease |
| `src/persistence/shadow_stores.py` | METADATA_ONLY | facade over the stores above (structure only) |
| `src/persistence/__init__.py`, `src/db/__init__.py`, alembic `__init__` | METADATA_ONLY | 1-36 lines |
| `src/persistence/{pending_actions,risk_reservations,day_risk,safe_mode_store,system_state}.py` | NOT_READ (other lanes) | `risk_reservations.py:386-430,561-673` read only for the approval race |
| `src/data/store.py` | DEEP_READ | atomic tmp+fsync+replace, never overwrite, Decimal(38,8) pinned |
| `src/data/backfill.py` | DEEP_READ (lines 186-1285) | closed-day rule, partial-day hold, dedup, rejection rollback, store-authoritative resume |
| `src/data/quality.py` | DEEP_READ | structural gate; gap warn-only |
| `src/data/backfill_cli.py` | NORMAL_READ (lines 770-900 + grep) | always `resume_from_store=True`; -1121 reroute to archive |
| `src/data/archive.py` | NORMAL_READ (`ArchiveKlineSource`, listing parser) | missing daily zip skipped, never interpolated; XML DOCTYPE/entity refused |
| `src/data/collector.py` | NORMAL_READ (lines 200-600 + grep of the rest) | OI / funding tick files, watermark, gap journal |
| `src/data/sufficiency.py` | NORMAL_READ (lines 1-116, 256-352 + grep) | funding hole rule (G-1102) |
| `src/data/coverage.py` | NORMAL_READ (`gap_ranges_for_files` 340-398, `report_symbol`) | single gap definition D-19 |
| `src/data/case_input.py` | NORMAL_READ (lines 76-90, 460-580, 690-850) | gap policy, funding cadence, terminal declarations |
| `src/data/universe_freeze.py` | NORMAL_READ (lines 1-90, 186-435) | point-in-time candidates incl. delisted and archive-only symbols; Decimal ranking |
| `src/data/minute_source.py` | NORMAL_READ (docstring + defs) | lazy per-day 1m reads, validated, holes kept, path confinement |
| `src/data/metadata.py`, `src/data/collect_list.py` | NORMAL_READ (docstrings + structure) | versioned insert-only metadata; collect list fails closed |
| `src/adapters/analytics_files.py` | NORMAL_READ (lines 1-40, 420-475, 905-922 + defs) | read-only loaders, `parse_constant` rejects NaN/Infinity, Decimal from strings only, output dir confinement |

## Verified Safe Areas
- **Approval consumption + ENTRY intent are atomic and single-use.** `consume_and_record_entry_intent` (`src/persistence/execution_state.py:262-349`) does `INSERT ... ON CONFLICT (approval_id, role) DO NOTHING RETURNING`, reads the approval `FOR UPDATE`, then a conditional `UPDATE approvals ... WHERE consumption_status='UNCONSUMED' AND status='APPROVED' AND approved_quantity = :bound AND approved_quantity >= :intended`; `rowcount != 1` raises inside the transaction, so the INSERT rolls back. A second approval of the same plan cannot create a second ENTRY: `uq_execution_intents_plan_role` and `uq_execution_intents_client_order_id` (`src/db/models.py`, class `ExecutionIntentRow`). A replay returns False before any quantity is read. It holds at READ COMMITTED because the arbiter is a unique index, not a Python check.
- **One decision per plan.** `uq_approvals_one_decided_per_plan` (partial unique on `trade_plan_id WHERE status NOT IN ('PENDING','EXPIRED')`, migration 0014) plus the conditional `UPDATE ... WHERE status='PENDING'` in a SAVEPOINT (`src/persistence/approvals.py:281-323`). Concurrent APPROVE vs SKIP of sibling rows: one hits the index and gets `ApprovalAlreadyDecided`.
- **APPROVE racing the expiry of its sibling row (EXPIRED is outside the index).** Reasoned in both orders with the reservation hook (`src/persistence/risk_reservations.py:386-430, 561-594`): if APPROVE locks the reservation first, the expiry's `UPDATE ... WHERE status='REQUESTED'` re-evaluates after the lock and matches 0 rows; if the expiry releases first, `reserve_in` reads the row `FOR UPDATE`, sees it is not REQUESTED and refuses, so the approval rolls back to PENDING. Neither order gives an approved plan without a counted reservation. Reasoned from the SQL text; not run against PostgreSQL.
- **Intent status moves are locked and table-checked.** `_advance` (`execution_state.py:571-607`) reads `FOR UPDATE` and calls `assert_transition`; trigger `trg_execution_intents_terminal_status` refuses a change out of ACKED / REJECTED for a writer that bypasses the store.
- **No silent NUMERIC rounding on the entity path.** `_guard_precision` (`entities.py:226-236`) refuses any Decimal that differs from `quantize_for_storage(value)` before INSERT / UPDATE; `insert_pending` does the same for `approved_quantity` (`approvals.py:171-174`). NUMERIC(38,18) therefore cannot round a quantity upward.
- **Out-of-order stream events cannot move stored order / position state backwards.** `update_order_exchange_state` and `update_position_snapshot` compare the event time under `FOR UPDATE` and again in the UPDATE's WHERE (`entities.py:571-608, 842-866`).
- **Journal is append-only and replay-idempotent.** `ON CONFLICT (journal_event_id) DO NOTHING` plus a field comparison (`journal.py:99-160`); UPDATE / DELETE / TRUNCATE are blocked by triggers (`0004_persistence_integrity.py:594-619`). Limit, recorded in the migration comment (line 555): the table owner can `DISABLE TRIGGER`, and the app connects as owner until Phase 26 (KNOWN).
- **Database waits are bounded and fail closed.** `connect_timeout` 3 s, `lock_timeout` 5 s, `statement_timeout` 10 s, pool wait 5 s, keepalives (`engine.py:33-93`); a connection-level error becomes `StoreUnavailable`, another DBAPI error `StoreFailure`, with no retry (`uow.py:44-60`). Session TimeZone is pinned to UTC and checked once per engine.
- **Migration chain is linear**, 0001 -> 0015, one head; each `down_revision` names the previous file. The downgrades of 0014 and 0015 refuse when data would be lost.
- **The analytics adapter cannot change operational state**: SELECTs only, plus `append_kill_gate_event`, which refuses any other event type (`analytics_store.py:248-254`).
- **ORM == migrations == domain enums (probe, no database).** `tmp/data_persistence_db/probe_ddl.py` renders revisions 0001 -> head as PostgreSQL SQL in Alembic offline mode and compiles `Base.metadata` for PostgreSQL: one head (`0015_order_event_time`); the same 20 tables; every `ck_/uq_/fk_/pk_/ix_` name present on both sides; `probe_ck.py`: 69 CHECK constraints, 0 text differences; `probe_enum.py`: every status CHECK list equals its domain enum (`OrderStatus`, `PositionStatus`, `SignalStatus`, `TradePlanStatus`, `ApprovalResult`, `ApprovalAction`, `ExecutionIntentStatus`, `OrderRole`, `ReleaseReason`, `ReservationStatus`, `PendingKind`, `PendingState`, `ComponentKind`, `ComponentSource`, `SystemStateKey`, `SetupType`, `SourceTimeframe`, `EntryModel`). No enum drift.
- **Types.** Probe output: 57 `TIMESTAMP WITH TIME ZONE`, 0 without; the only numeric type is `NUMERIC(38, 18)`; no FLOAT / REAL / DOUBLE anywhere in the migrations.
- **Nullable money columns are explicit "unknown", not zero.** `approvals.approved_quantity` NULL is refused at consume (`ApprovedQuantityMissing`, `execution_state.py:139-141`); `risk_reservations.required_margin` / `margin_entry_price` / `margin_leverage` are all-NULL or all-set by `ck_risk_reservations_margin_coherent`; `execution_intents.sized_realized_risk` NULL gives `NO_RISK_VALUE` in analytics; `orders.price` / `stop_price` NULL or `> 0`.
- **Constraint snapshot evidence is tamper-evident on read.** `_verified_snapshot` recomputes the sha256 and compares the denormalized columns; mismatch is `RowConflict` and `is_valid_for_live` answers False (`snapshots.py`).
- **Plan values are quantized before hashing and storage.** `src/core/planner.py:609-715` applies `quantize_for_storage` to prices, `risk_rate`, `risk_budget`, `suggested_quantity`, so `_guard_precision` does not reject normal plans and a re-read plan compares equal.
- **Raw Parquet is immutable and torn-write safe.** `atomic_write_parquet` (`src/data/store.py:64-99`) writes `.<name>.<pid>.tmp` in the same directory, fsyncs, refuses if the target exists, then `os.replace`; `publish_batch` / `publish_mark_batch` refuse heterogeneous symbol/interval batches (`store.py:175-182, 222-229`). The temp name cannot match the `date=*/part.parquet` glob. Limit stated in the docstring: check-then-replace is not atomic, safe only under one writer per key (no lock enforces it).
- **Only whole, closed UTC days are published.** `backfill_symbol_interval` clamps `effective_end = min(end_ms, start of today UTC)` and drops bars with `close_time > now` or `open_time >= effective_end` before the quality gate (`src/data/backfill.py:592-651`); in-loop it publishes every buffered date except the newest; at loop end a date is published only if `day_start + DAY <= effective_end` or it is the terminal day of a delivered contract, otherwise held and counted (`backfill.py:790-805`). REST `klines` is called without `endTime` (`backfill.py:150-153`), so an empty page means no later data, not an interior hole.
- **Corrupt pages are never published and never skipped.** Rows are marked seen only after the gate passes; a rejected page rolls the cursor back to `last_published + 1 interval` and the run raises `StructuralRejectionError` after 5 consecutive rejections (`backfill.py:653-753`). Gate rejects duplicates, OHLC violations, regressions, negatives, `close<=open`, mixed keys, non-finite or >8 fractional digits (`src/data/quality.py:145-274`), so the pinned `Decimal(38,8)` cast is exact.
- **Resume is store-authoritative.** The only production caller (`src/data/backfill_cli.py:794-812`) passes `resume_from_store=True`: `published_days` + `missing_day_runs` fetch only unpublished days, each segment ends at the midnight of the next published day (`backfill.py:955-983, 1139-1186`), so a lost or backward cursor cannot cause a republish or hide an older hole.
- **Collector ticks are journaled when they fail.** `async_oi_tick` and `async_funding_sweep` record a per-symbol gap row on an adapter error and a tick-wide gap row (then re-raise) on a write / commit error; watermarks and files are committed together (`src/data/collector.py:380-595`). A funding file already on disk from a rolled-back sweep counts as covered instead of wedging every later sweep (`collector.py:550-564`). Gap reasons are cut to the column width before insert (`collector.py:333-344`). Limit: an existing file is accepted without comparing its content.
- **Research universe has no survivorship bias by construction.** Candidates are every USDT PERPETUAL in exchangeInfo of any status plus archive-only USDT symbols; a symbol delivered before the ranking window, listed after it, with fewer than 30 full days or a zero-trade day is ineligible with a stated reason; ranking is Decimal with precision 60 and symbol tie-break (`src/data/universe_freeze.py:210-229, 364-392`).
- **Analytics file inputs fail closed and stay Decimal.** JSON NaN / Infinity refused (`parse_constant`), decimals accepted only as strings and must be finite, datetimes must be UTC-aware, output directory confined to the reports root (`src/adapters/analytics_files.py:420-475, 909-922`).

## Decision review
| Decision / doc rule | Verdict | Yardstick | Reason |
|---|---|---|---|
| D-04 immutable per-day Parquet, no overwrite | SOUND | research reproducibility practice | Hashable, append-only raw data. Cost: an exchange-side correction of a published day can only be fixed by a "new version" flow that does not exist in `src/data` (the error text names it). Acceptable for V1 |
| D-13 / F-402 publish only whole closed UTC days | SOUND | arithmetic of the paginator (read) | Removes the forming candle and partial days that immutability would freeze forever |
| D-10 structural reject, gaps warn-only at publish | SOUND | fail-closed data practice | Gaps are real exchange outages; they are refused later by the single D-19 gap rule in the case builder |
| D-15 zero-trade bars are valid data | SOUND | exchange behaviour (illiquid minutes exist) | A missing bar stays a gap; zero volume is not interpolated |
| CR-02 store-authoritative resume | SOUND | failure analysis (lost or stale cursor) | A cursor can no longer hide an older hole or force a republish |
| D-36 funding hole = gap longer than 8 h + 60 s for every series | DOUBTFUL | probe + Binance `fundingIntervalHours` per symbol | Hides a missed tick of a 4 h (or 1 h) series, against its own docstring (G-1102) |
| D-06..D-09 / D039 point-in-time universe, top 12 by 30-day quote volume before dataset start | SOUND | survivorship-bias practice | Delisted and archive-only symbols are candidates; the number 12 is a choice, not derived (CANNOT_JUDGE on the size) |
| READ COMMITTED with unique indexes as arbiters (approval consume, one decision per plan) | SOUND | PostgreSQL semantics, SQL text read | Correctness rests on constraints, not on isolation level |
| NUMERIC(38,18) + refuse-don't-round precision guard | SOUND | probe of DDL + guard read | No silent rounding of quantities or prices |
| Journal append-only by triggers while the app connects as table owner until Phase 26 | DOUBTFUL | PostgreSQL privilege model | The owner role can `DISABLE TRIGGER`; protection is against bugs, not against a compromised app (KNOWN, migration 0004 comment) |
| DB timeouts connect 3 s / lock 5 s / statement 10 s, no retry | SOUND | fail-closed rule | Bounded waits, errors typed as unavailable vs failure. The numbers are not derived but are conservative |
| 24-DEFERRED 20D-01 "CLOSED [DESIGN]" (fills ledger / order lifecycle) | WRONG | static trace | No production writer of `fills`; `orders.local_status` never leaves NEW (G-1101) |

## Findings

### G-1101
- **Severity:** MEDIUM now (Demo) / HIGH on mainnet with placement enabled
- **Confidence:** CONFIRMED (static trace: the writer has no caller)
- **Classification:** GAP (and a deferred item recorded as closed that is not)
- **Category:** persistence / evidence
- **Component:** fills ledger, order lifecycle, live analytics input
- **File:** `src/persistence/entities.py`, `src/live/stream_persistence.py`, `src/analytics/live_outcomes.py`
- **Lines:** `entities.py:692-739` (`record_fill`), `stream_persistence.py:258-298`, `live_outcomes.py:261-271`
- **Rule:** `.planning/phases/24-live-runtime-composition-demo/24-CONTEXT.md:36` (D-10: "Positions table, fills ledger and `Order` rows ... are built here as the persistence the stream feeds"); `24-DEFERRED.md:56` row 20D-01 "CLOSED [DESIGN]"; old G4-043.
- **Known-prior:** KNOWN:24-DEFERRED 20D-01, recorded CLOSED; that record is the part that is wrong. R-06 defers only the *position* lifecycle.
- **Evidence:** `grep -rn "record_fill\|fill_to_row" src` finds only the definition in `entities.py` and the mapper: no production code writes the `fills` table. The stream writer inserts an `orders` row with `local_status` NEW (or UNKNOWN) and then calls only `update_order_exchange_state`, whose docstring says "`local_status` is never touched" (`entities.py:543`); `transition_order` is called only when the stored status is UNKNOWN (`stream_persistence.py:283`). So in the live process `fills` stays empty and `orders.local_status` stays `NEW` after a fill, a cancel or an expiry. The consumer of these tables, the analytics CLI, calls `normalize_live_outcomes(rows.signals, rows.plans, rows.orders, rows.fills)` (`src/analytics/cli.py:580`), and that function has `if not entry_fills: continue  # not a candidate: no entry order with a fill` (`live_outcomes.py:270-271`).
- **Expected:** every fill the exchange reports for a system order is stored once in `fills` (the store method and the unique key `(order_id, exchange_trade_id)` exist for that), and an order row ends FILLED / CANCELED / EXPIRED.
- **Actual:** no fill is ever stored. LIVE evidence built from the database has zero trades and zero INCOMPLETE notes, whatever happened on the exchange. Fill money survives only as day-scoped rows in `daily_loss_components` (signed PnL and commission amounts; no price, quantity or order link).
- **Reproduction:** `grep -rn "record_fill" snapshot/src` gives one hit (the `def`). Read `stream_persistence.py:258-298`.
- **Impact:** now: the Phase 25 Demo campaign cannot be evaluated from the database; the live report shows no trades, silently, not as an error. The 21/21 smoke does not exercise this. Mainnet: no durable per-fill record (price, quantity, commission, maker flag) of real-money trades in the system of record, and any live report or gate fed by `read_live_rows` sees nothing, so a losing live record cannot appear there. Binance keeps trade history for a limited window, so the gap becomes permanent with time.
- **Why tests miss it:** `tests/test_live_stream_persistence_pg.py` and the entity-store tests call store methods directly; nothing asserts that a fill delivered by the stream ends in `fills`. The `*_pg.py` files are skipped without `TEST_DATABASE_URL`.
- **Remediation:** add a fills writer on the stream / REST fill path (same writer thread, same transaction as the order update), move `local_status` along the transition table from stream events, and reopen 20D-01 until a test proves: stream fill -> `fills` row -> `normalize_live_outcomes` candidate.

### G-1102
- **Severity:** LOW now / LOW on mainnet (research cost accuracy, not order safety)
- **Confidence:** CONFIRMED (probe `tmp/data_persistence_db/probe_funding.py`)
- **Classification:** DEFECT (the code does not do what its own docstring and D-36 text claim)
- **Category:** data quality / research input
- **Component:** funding gap definition (case input builder, sufficiency report, engine coverage check)
- **File:** `src/data/case_input.py`, `src/data/sufficiency.py`, `src/backtest/funding.py`
- **Lines:** `case_input.py:79-81, 466-473, 694-712`; `sufficiency.py:105-106, 299-349`; `funding.py:203-212, 240`
- **Rule:** D-36 (funding coverage); `src/backtest/funding.py:208-210`: "every consecutive difference must be at most `G`... so a missed tick in a 4 h series that the 8 h grid test would hide is still found".
- **Known-prior:** none found. `lanes/exchange_facts.md:217` notes 1 h / 2 h intervals are not modelled (related, not the same).
- **Evidence:** every funding hole test uses one tolerance `G = FUNDING_MAX_CADENCE + FUNDING_JITTER` = 8 h + 60 s (`case_input.py:81`, `funding.py:240`, `sufficiency.py:105-106`), whatever the inferred cadence. `infer_funding_cadence_ms` is used only for the `missing` count. Probe: a 4 h series over two days with the 08:00 tick removed -> inferred cadence 4.0 h; `gap_ranges_for_files(..., step_ms=4h, max_step_ms=8h+60s)` returns `[]`; `funding_holes` returns `()`; `check_funding_coverage` for a holding window 01:00-20:00 that spans the missing instant returns `()` and does not raise.
- **Expected:** for a series whose cadence is 4 h (or shorter), a missing instant is a hole: the builder refuses or the gap must be declared.
- **Actual:** up to one consecutive missing tick of a 4 h series (and up to seven of a 1 h series, a cadence Binance can set per symbol via `fundingIntervalHours`) is accepted silently; the engine then charges no funding for that instant.
- **Reproduction:** run `probe_funding.py` (PYTHONPATH = snapshot).
- **Impact:** funding cost understated by one settlement per missed tick. Size: at 0.01 % per settlement on a notional of 50 % of equity (0.5 % risk, 1 % stop), one missed tick is 0.005 % of equity, about 0.01 R. Small per trade; it biases research results toward profit only when collector holes cluster in held windows. No order-path effect.
- **Why tests miss it:** the docstring claim and the tolerance were written together; a test with a 4 h series and one missing tick asserting a hole would fail today.
- **Remediation:** use `inferred_cadence + jitter` as the tolerance (keep 8 h + jitter only as the floor for the default), or record the exchange `fundingIntervalHours` history; correct the docstring otherwise.

## Owner decisions
- **G-1101 fills ledger before the Phase 25 Demo campaign?** Today a Demo trade that fills, hits its stop and closes leaves one `orders` row with `local_status = NEW` and zero `fills` rows; `normalize_live_outcomes` therefore reports 0 trades for a campaign of, say, 20 filled trades with net -3 R. Options: (a) build the fills writer and lifecycle moves before the campaign; (b) evaluate the campaign from exchange trade history exported by hand (Binance keeps it for a limited window); (c) accept the gap and record it. The owner chooses; the audit does not.

## Open Questions
- (lane backtest) `src/backtest/funding.py:203-212` claims the engine check finds a missed tick in a 4 h series; the probe in G-1102 shows it does not. The backtest lane should judge the cost effect on recorded research runs.
- (lane exchange facts) Do any live-5 or research-universe symbols run on a 1 h or 2 h funding interval in the dataset window? `infer_funding_cadence_ms` knows only 4 h and 8 h.
- (lane ops) Which database role does the live process use on the host? With the table owner, the journal triggers can be disabled (KNOWN until Phase 26).
- (lane live composition) Is there any other writer that moves `orders.local_status` or inserts `fills` outside `src/` (scripts, Demo smoke)? None found in `src/`.
- Not checked: the remaining 1,000 lines of `backfill_cli.py` (window planning, archive adoption), `coverage.py` DuckDB views and `case_input.py` hashing beyond the parts cited; `collector.py` main loop and health (lines 818-1235) only grepped.

## DONE
