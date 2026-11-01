"""The client-id index: the user-data router's `OrderLookup`, fed from intent client ids (P-4).

An exchange order the project did not place is an unknown stream order. A fill can arrive before
any store row for a freshly sent entry is visible, so the lookup the router consults must already
know the entry id when the entry is sent. This index is that lookup: in memory only, registered by
the execution service BEFORE `execute_approved_plan` is awaited (research P-4), and never backed
by a store (a store read on the router path would put I/O on the stream callback).

Ids are the deterministic ones of `src/execution/order_ids.py`: the index checks the family
prefix, the role code and the plan-hash prefix of every id it is given and refuses anything else,
so a malformed or foreign id never becomes a "known" order. `local_order_id` defaults to the
client id; the persistence wiring that maps an id to its `orders` row replaces it later.

The index is touched from the event loop thread only (registration in the execution service,
lookups in the router callback), so it holds no lock.
"""

from __future__ import annotations

from src.adapters.binance_userdata_router import KnownOrder
from src.domain.enums import OrderRole, OrderStatus
from src.execution.order_ids import (
    derive_algo_client_id,
    derive_client_order_id,
    plan_hash_prefix_of,
    role_of_client_id,
)

_PLAN_PREFIX_LEN = 29  # the plan-hash characters shared by the three id families
_PROTECTIVE_ROLES: tuple[OrderRole, ...] = (
    OrderRole.STOP_LOSS,
    OrderRole.TAKE_PROFIT_1,
    OrderRole.TAKE_PROFIT_2,
)


def _check_id(client_id: str, *, plan_hash: str, role: str, algo: bool) -> None:
    """Refuse an id that is not the deterministic id of `(plan_hash, role)` in its family."""
    expected = (
        derive_algo_client_id(plan_hash=plan_hash, role=role)
        if algo
        else derive_client_order_id(plan_hash=plan_hash, role=role)
    )
    if client_id != expected:
        raise ValueError("client id is not the deterministic id of this plan and role")
    if (
        plan_hash_prefix_of(client_id) != plan_hash[:_PLAN_PREFIX_LEN]
        or role_of_client_id(client_id) != role
    ):  # defensive: the derivation and the readers must agree
        raise ValueError("client id does not carry the plan hash prefix and role it was built from")


class ClientIdIndex:
    """In-memory `OrderLookup` over the client ids the live process has sent or will send."""

    def __init__(self) -> None:
        self._orders: dict[str, KnownOrder] = {}
        self._algos: dict[str, KnownOrder] = {}

    def register_entry(
        self,
        *,
        plan_hash: str,
        client_order_id: str,
        symbol: str,
        local_order_id: str | None = None,
    ) -> KnownOrder:
        """Make the ENTRY id of `plan_hash` known; returns the stored record (idempotent)."""
        _check_id(client_order_id, plan_hash=plan_hash, role=OrderRole.ENTRY.value, algo=False)
        known = KnownOrder(
            local_order_id=local_order_id or client_order_id,
            client_id=client_order_id,
            symbol=symbol,
            role=OrderRole.ENTRY,
            local_status=OrderStatus.NEW,
        )
        return self._orders.setdefault(client_order_id, known)

    def register_algo(
        self,
        *,
        plan_hash: str,
        client_algo_id: str,
        symbol: str,
        role: OrderRole,
        local_order_id: str | None = None,
    ) -> KnownOrder:
        """Make a protective (algo) id of `plan_hash` known; returns the stored record."""
        if role is OrderRole.ENTRY:
            raise ValueError("an algo id never carries the ENTRY role")
        _check_id(client_algo_id, plan_hash=plan_hash, role=role.value, algo=True)
        known = KnownOrder(
            local_order_id=local_order_id or client_algo_id,
            client_id=client_algo_id,
            symbol=symbol,
            role=role,
            local_status=OrderStatus.NEW,
        )
        return self._algos.setdefault(client_algo_id, known)

    def register_protective_algos(self, *, plan_hash: str, symbol: str) -> None:
        """Make the stop and both take-profit ids of `plan_hash` known before they are placed.

        The ids are deterministic, so the index can know them when the entry is sent: the
        ALGO_UPDATE of a leg the coordinator places while the process runs is then a known order
        (first Demo run, 2026-11-01: each leg was an unknown stream order). Idempotent.
        """
        for role in _PROTECTIVE_ROLES:
            self.register_algo(
                plan_hash=plan_hash,
                client_algo_id=derive_algo_client_id(plan_hash=plan_hash, role=role.value),
                symbol=symbol,
                role=role,
            )

    def known_order(self, client_order_id: str) -> KnownOrder | None:
        return self._orders.get(client_order_id)

    def known_algo(self, client_algo_id: str) -> KnownOrder | None:
        return self._algos.get(client_algo_id)


__all__ = ["ClientIdIndex"]
