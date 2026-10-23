"""Operational persistence layer (Phase 17): synchronous SQLAlchemy 2.0 repositories.

Module map (no re-exports; `tests/test_persistence_exit_evidence_pg.py` checks that this list
names every module of the package):

  - `errors`               typed persistence failures callers translate to NO_TRADE / SAFE_MODE
  - `engine`               engine factory: UTC pinned per session, pool_pre_ping, fail closed
  - `uow`                  `OperationalDatabase.transaction()` unit of work (D-03)
  - `journal`              `PgJournalStore`: append-only, replay-idempotent journal (D-10)
  - `approvals`            `PgApprovalStore`: durable approvals and Telegram callback state
  - `execution_state`      `PgExecutionStateStore`: durable approval consumption and
                           write-ahead execution intents (D-13, D-14, D-15)
  - `entities`             `PgTradingEntityStore`: Signal, TradePlan, Order, Fill and Position
                           with in-transaction state machines (DOMN-04), evidence-gated
                           UNKNOWN exits and the Order exchange-state writer (Phase 18)
  - `snapshots`            `PgPlanConstraintSnapshotStore`: per-plan exchange constraints
  - `system_state`         `PgSystemStateStore`: SAFE_MODE, enablement and kill gate (D-22)
  - `safe_mode_store`      `PgSafeModeStateStore`: the SafeModeStateStore seam over `system_state`
                           (durable SAFE_MODE, Phase 20)
  - `pending_actions`      `PgPendingActionStore`: the durable intent of a protective action the
                           REST gate refused (Phase 20, plan 20-14)
  - `lot_filters`         `PgLotFilterStore`: the last validated lot filters of each symbol, used
                           only by the emergency close when exchangeInfo is unreadable (Phase 20,
                           plan 20-18)
  - `day_risk`            `PgDayRiskStore`: the UTC day's risk state (base, DAILY_STOP latch,
                           warning mark) and its daily-loss components (Phase 21, plan 21-09)
  - `paper_runtime_state`  `PgRuntimeState`: journal-only paper runtime state (Phase 16)
  - `shadow_stores`        `PgShadowStores`: the SHADOW chain's composed stores (Phase 16)

The domain model stays the authority (D-02): repositories accept and return domain
objects or the stdlib records declared next to the Protocol that consumes them; ORM
rows never reach strategy or execution code.
"""
