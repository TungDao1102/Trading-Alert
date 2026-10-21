"""The local side of the reconcile compare (Phase 20, plan 20-12; D-13, D-30).

Where the local data comes from, by name:

  1. the protection coordinator's `protections()` views (rebuilt from the durable intents and the
     journal after a restart, plan 20-19, D-30); each plan's state says what should rest on the
     exchange right now;
  2. `ExecutionIntentStore.list_unresolved_intents()`: SENT and UNKNOWN rows are legs that may
     exist on the exchange although no coordinator state mentions them yet (a placement whose
     answer was lost, Q5), so an order that may exist is never reported foreign.

No `positions` table and no `Order` row is read: Phase 20 builds no positions ledger (D-13), and a
table filled from Binance's own read would not be an independent source. INTENDED rows are never
added: `mark_sent` commits before the send, so INTENDED means nothing was sent, and an exchange
order under such an id is rightly a divergence.

What each tracked plan state contributes (the eleven names of `ProtectionState`; a parity test on
the execution side imports the enum and compares the names, this module imports nothing from
`src.execution.protection`):

  state                 entry order            stop loss       take profits   position
  AWAITING_FILL         NEW                    if confirmed*   no             no
  ENTRY_UNRESOLVED      SUBMITTING             if confirmed*   no             no
  UNPROTECTED           PARTIALLY_FILLED       if confirmed*   no             yes
  PROTECTED_ENTRY_OPEN  PARTIALLY_FILLED       if confirmed*   no             yes
  PROTECTED             no                     if confirmed*   no             yes
  COMPLETE              no                     if confirmed*   TP1, TP2       yes
  TP_UNAVAILABLE        no                     if confirmed*   no             yes
  CLOSE_REQUIRED        no                     if confirmed*   no             yes
  CLOSE_FAILED          no                     if confirmed*   no             yes
  FLAT                  no                     no              no             no
  ENTRY_ENDED_NO_FILL   no                     no              no             no

  * `stop_confirmed_at_utc` is set and `stop_lost_at_utc` is not. An entry order is emitted only
    while `entry_terminal_at_utc` is None, in the states that list one.

The position intent carries what compare v2 needs (plan 20-04): `plan_hash`, `expected_side`
(from the plan side LONG or SHORT) and `max_abs_amount` (the plan's entry quantity). A value the
view does not carry stays None, which compare reads as AMBIGUOUS_POSITION_OWNER, never as
agreement. A state name this table does not know raises ValueError: the caller fails closed.

The active plans (plan 20-20, owner decision O-D): `LocalIntent.active_plans` lists, once per
plan hash, every tracked plan whose state is not FLAT or ENTRY_ENDED_NO_FILL, plus every plan that
is not tracked at all but is named by an unresolved ENTRY intent (SENT or UNKNOWN: the order may
exist). A tracked plan's own state decides, so an unresolved ENTRY row of a FLAT plan does not
reactivate it. Compare reads the list as evidence of ownership only: more than one plan for one
symbol is a divergence, and no plan is ever picked. A plan known only to the journal and not yet
rebuilt into `protections()` is not seen (the loop skips the tick until the restore is complete).

Pure module: stdlib, `src.domain.enums`, the id derivations and the compare carriers. No clock,
no I/O, no adapter, no store.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Protocol

from src.domain.enums import OrderRole, OrderStatus
from src.execution.order_ids import derive_algo_client_id, derive_client_order_id
from src.reconcile.compare import (
    LocalActivePlan,
    LocalAlgoIntent,
    LocalOrderIntent,
    LocalPositionIntent,
)

# The plan states that hold nothing on the exchange and no exposure.
STATE_FLAT: str = "FLAT"
STATE_ENTRY_ENDED_NO_FILL: str = "ENTRY_ENDED_NO_FILL"
INACTIVE_STATE_NAMES: frozenset[str] = frozenset({STATE_FLAT, STATE_ENTRY_ENDED_NO_FILL})

#: The unresolved intent statuses whose leg may exist on the exchange (INTENDED never does).
_MAY_EXIST_STATUSES: frozenset[str] = frozenset({"SENT", "UNKNOWN"})

_ONE_WAY_POSITION_SIDE = "BOTH"
_LONG = "LONG"
_SHORT = "SHORT"


@dataclass(frozen=True)
class _StateRule:
    """What a state contributes: the local status of its entry order (None = none), the exposure
    flag and whether the take-profit legs rest."""

    entry_status: str | None
    position: bool
    take_profits: bool


_NEW = OrderStatus.NEW.value
_SUBMITTING = OrderStatus.SUBMITTING.value
_PARTIAL = OrderStatus.PARTIALLY_FILLED.value

STATE_RULES: Mapping[str, _StateRule] = MappingProxyType(
    {
        "AWAITING_FILL": _StateRule(_NEW, position=False, take_profits=False),
        "ENTRY_UNRESOLVED": _StateRule(_SUBMITTING, position=False, take_profits=False),
        "UNPROTECTED": _StateRule(_PARTIAL, position=True, take_profits=False),
        "PROTECTED_ENTRY_OPEN": _StateRule(_PARTIAL, position=True, take_profits=False),
        "PROTECTED": _StateRule(None, position=True, take_profits=False),
        "COMPLETE": _StateRule(None, position=True, take_profits=True),
        "TP_UNAVAILABLE": _StateRule(None, position=True, take_profits=False),
        "CLOSE_REQUIRED": _StateRule(None, position=True, take_profits=False),
        "CLOSE_FAILED": _StateRule(None, position=True, take_profits=False),
        STATE_FLAT: _StateRule(None, position=False, take_profits=False),
        STATE_ENTRY_ENDED_NO_FILL: _StateRule(None, position=False, take_profits=False),
    }
)

#: Role of an unresolved intent row -> True for the normal-order family, False for algo legs.
_NORMAL_ROLES: frozenset[str] = frozenset({OrderRole.ENTRY.value})
_ALGO_ROLES: frozenset[str] = frozenset(
    {
        OrderRole.STOP_LOSS.value,
        OrderRole.TAKE_PROFIT_1.value,
        OrderRole.TAKE_PROFIT_2.value,
    }
)


class PlanProtectionLike(Protocol):
    """The read-only fields of `PlanProtection` this module reads."""

    @property
    def plan_hash(self) -> str: ...

    @property
    def symbol(self) -> str: ...

    @property
    def state(self) -> Any: ...

    @property
    def stop_confirmed_at_utc(self) -> Any: ...

    @property
    def entry_terminal_at_utc(self) -> Any: ...

    @property
    def stop_lost_at_utc(self) -> Any: ...

    @property
    def side(self) -> str | None: ...

    @property
    def entry_quantity(self) -> Decimal | None: ...

    @property
    def entry_client_order_id(self) -> str | None: ...


class IntentRecordLike(Protocol):
    """The read-only fields of `IntentRecord` this module reads."""

    @property
    def role(self) -> str: ...

    @property
    def plan_hash(self) -> str: ...

    @property
    def symbol(self) -> str: ...

    @property
    def client_order_id(self) -> str | None: ...

    @property
    def algo_client_id(self) -> str | None: ...

    @property
    def intent_status(self) -> Any: ...


@dataclass(frozen=True)
class LocalIntent:
    """The three local sequences of one compare, each sorted by symbol then id."""

    orders: tuple[LocalOrderIntent, ...]
    algos: tuple[LocalAlgoIntent, ...]
    positions: tuple[LocalPositionIntent, ...]
    active_plans: tuple[LocalActivePlan, ...] = ()

    def compare_kwargs(self) -> dict[str, tuple[Any, ...]]:
        """The local keywords of `compare(...)`; the loop passes them with `**`, so a later plan
        can add a local input here without editing the loop."""
        return {
            "local_open_orders": self.orders,
            "local_open_algos": self.algos,
            "local_open_positions": self.positions,
            "local_active_plans": self.active_plans,
        }


def _name(value: Any) -> str:
    """The text of a str-enum or plain string (never an exception text)."""
    raw = getattr(value, "value", value)
    if not isinstance(raw, str) or raw == "":
        raise ValueError("a state, role or status must be a non-empty string")
    return raw


def derive_local_intent(
    protections: Iterable[PlanProtectionLike],
    unresolved: Iterable[IntentRecordLike],
) -> LocalIntent:
    """The local intent of one tick.

    Args:
        protections: the coordinator's `protections()` rows.
        unresolved: `list_unresolved_intents()` rows (INTENDED, SENT, UNKNOWN).

    Raises:
        ValueError: a state name the table does not know, or an id that cannot be derived from a
            malformed plan hash. The caller treats this as a failed local read.
    """
    orders: dict[str, LocalOrderIntent] = {}
    algos: dict[str, LocalAlgoIntent] = {}
    positions: list[LocalPositionIntent] = []
    active: dict[str, LocalActivePlan] = {}
    tracked_hashes: set[str] = set()

    for plan in protections:
        tracked_hashes.add(plan.plan_hash)
        state = _name(plan.state)
        rule = STATE_RULES.get(state)
        if rule is None:
            raise ValueError(f"unknown protection state {state!r}")
        if rule.entry_status is not None and plan.entry_terminal_at_utc is None:
            order_id = plan.entry_client_order_id or derive_client_order_id(
                plan_hash=plan.plan_hash, role=OrderRole.ENTRY.value
            )
            orders.setdefault(
                order_id,
                LocalOrderIntent(
                    client_order_id=order_id,
                    symbol=plan.symbol,
                    order_role=OrderRole.ENTRY.value,
                    status=rule.entry_status,
                    plan_hash=plan.plan_hash,
                ),
            )
        if state not in INACTIVE_STATE_NAMES:
            active.setdefault(
                plan.plan_hash, LocalActivePlan(plan_hash=plan.plan_hash, symbol=plan.symbol)
            )
            if plan.stop_confirmed_at_utc is not None and plan.stop_lost_at_utc is None:
                _add_algo(algos, plan, OrderRole.STOP_LOSS.value)
            if rule.take_profits:
                _add_algo(algos, plan, OrderRole.TAKE_PROFIT_1.value)
                _add_algo(algos, plan, OrderRole.TAKE_PROFIT_2.value)
        if rule.position:
            positions.append(_position_of(plan))

    for row in unresolved:
        if _name(row.intent_status) not in _MAY_EXIST_STATUSES:
            continue
        role = _name(row.role)
        if role in _NORMAL_ROLES:
            if row.plan_hash not in tracked_hashes:
                active.setdefault(
                    row.plan_hash, LocalActivePlan(plan_hash=row.plan_hash, symbol=row.symbol)
                )
            order_id = row.client_order_id or derive_client_order_id(
                plan_hash=row.plan_hash, role=role
            )
            orders.setdefault(
                order_id,
                LocalOrderIntent(
                    client_order_id=order_id,
                    symbol=row.symbol,
                    order_role=role,
                    status=_SUBMITTING,
                    plan_hash=row.plan_hash,
                ),
            )
        elif role in _ALGO_ROLES:
            algo_id = row.algo_client_id or derive_algo_client_id(
                plan_hash=row.plan_hash, role=role
            )
            algos.setdefault(
                algo_id,
                LocalAlgoIntent(
                    client_algo_id=algo_id,
                    symbol=row.symbol,
                    order_role=role,
                    status=_SUBMITTING,
                    plan_hash=row.plan_hash,
                ),
            )
        else:
            raise ValueError(f"unknown intent role {role!r}")

    return LocalIntent(
        orders=tuple(sorted(orders.values(), key=lambda o: (o.symbol, o.client_order_id))),
        algos=tuple(sorted(algos.values(), key=lambda a: (a.symbol, a.client_algo_id))),
        positions=tuple(sorted(positions, key=lambda p: (p.symbol, p.plan_hash or ""))),
        active_plans=tuple(sorted(active.values(), key=lambda a: (a.symbol, a.plan_hash))),
    )


def _add_algo(algos: dict[str, LocalAlgoIntent], plan: PlanProtectionLike, role: str) -> None:
    algo_id = derive_algo_client_id(plan_hash=plan.plan_hash, role=role)
    algos.setdefault(
        algo_id,
        LocalAlgoIntent(
            client_algo_id=algo_id,
            symbol=plan.symbol,
            order_role=role,
            status=_NEW,
            plan_hash=plan.plan_hash,
        ),
    )


def _position_of(plan: PlanProtectionLike) -> LocalPositionIntent:
    """The exposure of a plan after a first fill, for compare's signed bound check (D-01a)."""
    side = plan.side if plan.side in (_LONG, _SHORT) else None
    quantity = plan.entry_quantity
    bound = quantity if isinstance(quantity, Decimal) and quantity > 0 else None
    if bound is not None and side == _SHORT:
        amount: Decimal | None = -bound
    else:
        amount = bound
    return LocalPositionIntent(
        symbol=plan.symbol,
        position_side=_ONE_WAY_POSITION_SIDE,
        position_amt=amount,
        plan_hash=plan.plan_hash,
        expected_side=side,
        max_abs_amount=bound,
    )


__all__ = [
    "INACTIVE_STATE_NAMES",
    "STATE_RULES",
    "IntentRecordLike",
    "LocalIntent",
    "PlanProtectionLike",
    "derive_local_intent",
]
