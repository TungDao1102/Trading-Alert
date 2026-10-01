"""Operational persistence layer (Phase 17): synchronous SQLAlchemy 2.0 repositories.

Module map (no re-exports, so later plans never edit this file):

  - `errors`           typed persistence failures callers translate to NO_TRADE / SAFE_MODE
  - `engine`           engine factory: UTC pinned per session, pool_pre_ping, fail closed
  - `uow`              `OperationalDatabase.transaction()` unit of work (D-03)
  - `execution_state`  `PgExecutionStateStore`: durable approval consumption and
                       write-ahead execution intents (D-13, D-14, D-15)

The domain model stays the authority (D-02): repositories accept and return domain
objects or the stdlib records declared next to the Protocol that consumes them; ORM
rows never reach strategy or execution code.
"""
