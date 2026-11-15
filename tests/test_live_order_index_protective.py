"""The index knows the stop and both take-profit ids before the coordinator places them."""

from __future__ import annotations

from src.domain.enums import OrderRole
from src.execution.order_ids import derive_algo_client_id
from src.live.order_index import ClientIdIndex

PLAN_HASH = "ab" * 32
ROLES = (OrderRole.STOP_LOSS, OrderRole.TAKE_PROFIT_1, OrderRole.TAKE_PROFIT_2)


def test_register_protective_algos_makes_all_three_legs_known_with_their_roles() -> None:
    index = ClientIdIndex()

    index.register_protective_algos(plan_hash=PLAN_HASH, symbol="BTCUSDT")

    for role in ROLES:
        known = index.known_algo(derive_algo_client_id(plan_hash=PLAN_HASH, role=role.value))
        assert known is not None
        assert (known.symbol, known.role) == ("BTCUSDT", role)


def test_register_protective_algos_is_idempotent_and_leaves_other_plans_unknown() -> None:
    index = ClientIdIndex()
    index.register_protective_algos(plan_hash=PLAN_HASH, symbol="BTCUSDT")
    index.register_protective_algos(plan_hash=PLAN_HASH, symbol="BTCUSDT")

    other = derive_algo_client_id(plan_hash="cd" * 32, role=OrderRole.STOP_LOSS.value)
    assert index.known_algo(other) is None
