"""The live rig over PostgreSQL stores (plan 24-28): the real stores in place of the dict doubles.

TEST_ONLY: nothing here is production code and no production module imports it. `make_live_pg_rig`
is `make_live_rig` with the `stores`, `intents` and `journal` overrides set to the PostgreSQL
classes of `src.live.wiring.build_pg_stores` over one database; everything else (the fake
exchange, the bot, the virtual clock, the desk, the confirm flow, the service, the manager) is the
rig's. `PgStoresView` gives the PostgreSQL shadow store the three test-side reads the rig and the
tests use on the dict store (`approvals`, `plans`, `journal_of_type`) and delegates the rest.

A second process is a second engine over the same database (`pg_stores_on`), so two presses
really are two connections and the database's consume rule is the arbiter.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from src.db.mappers import approval_from_row, journal_from_row
from src.db.models import ApprovalRow, JournalEventRow
from src.domain.approval import Approval
from src.domain.journal import JournalEvent
from src.live.wiring import LiveStoreSet, build_pg_stores
from src.persistence.engine import make_sync_engine
from src.persistence.uow import OperationalDatabase

from tests.support.live_rig import LiveRig, make_live_rig


class _Approvals:
    def __init__(self, db: OperationalDatabase) -> None:
        self._db = db

    def values(self) -> list[Approval]:
        with self._db.transaction() as session:
            rows = session.execute(select(ApprovalRow)).scalars().all()
            return [approval_from_row(row) for row in rows]


class _Plans:
    def __init__(self, shadow: Any) -> None:
        self._shadow = shadow

    def get(self, trade_plan_id: str) -> Any:
        return self._shadow.get_trade_plan(trade_plan_id)


class PgStoresView:
    """`PgShadowStores` plus the dict-store reads of the rig; every other name is delegated."""

    def __init__(self, store_set: LiveStoreSet) -> None:
        self._store_set = store_set
        self._shadow = store_set.shadow
        self.approvals = _Approvals(store_set.db)
        self.plans = _Plans(store_set.shadow)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._shadow, name)

    def journal_of_type(self, event_type: str) -> list[JournalEvent]:
        with self._store_set.db.transaction() as session:
            rows = (
                session.execute(
                    select(JournalEventRow).where(JournalEventRow.event_type == event_type)
                )
                .scalars()
                .all()
            )
            return [journal_from_row(row) for row in rows]


@dataclass(frozen=True)
class PgConnection:
    """One process' engine and stores over the database."""

    engine: Engine
    store_set: LiveStoreSet
    view: PgStoresView


@contextmanager
def pg_stores_on(url: str) -> Iterator[PgConnection]:
    """A fresh engine and stores (what another process, or a restarted one, would build)."""
    engine = make_sync_engine(url)
    try:
        store_set = build_pg_stores(OperationalDatabase(engine))
        yield PgConnection(engine=engine, store_set=store_set, view=PgStoresView(store_set))
    finally:
        engine.dispose()


async def make_live_pg_rig(connection: PgConnection, **overrides: Any) -> LiveRig:
    """`make_live_rig` over the PostgreSQL stores of `connection`."""
    return await make_live_rig(
        stores=connection.view,
        intents=connection.store_set.execution_state,
        journal=connection.store_set.journal,
        **overrides,
    )


__all__ = ["PgConnection", "PgStoresView", "make_live_pg_rig", "pg_stores_on"]
