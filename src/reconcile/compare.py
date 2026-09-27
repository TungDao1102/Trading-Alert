"""Three-source compare: local intent vs exchange truth.

Per D-03: the reconciler compares local intent (orders in PLANNED /
NEW / PARTIALLY_FILLED states; positions marked OPEN) against three
exchange-truth sources:
  1. open normal orders (Binance `current_all_open_orders`)
  2. open algo orders (Binance `current_all_algo_open_orders`)
  3. positions (Binance `position_information_v3`)

It produces a typed `CompareDiff` whose `agreement` flag tells the
caller whether to enter SAFE_MODE, and whose `divergences` list drives
the SAFE_MODE transition (any divergence enters SAFE_MODE) and the
sweeper's cancel list (`orphan_protectives` are the only divergences
the sweeper is authorised to act on).

Divergence kinds (the only kinds the reconciler emits):

  - ORPHAN_PROTECTIVE: local algo protective (SL/TP1/TP2) with no
    matching local position AND no exchange position. Sweeper target.
  - ENTRY_WITHOUT_PROTECTIVE: local normal ENTRY with no matching
    algo protective for the same symbol (drives SAFE_MODE; never
    swept — the sweeper never places rescue protection per Pitfall 1).
  - UNSYNCED_NORMAL: local normal order with no matching exchange
    normal order (the order disappeared or was filled externally).
  - UNSYNCED_ALGO: local algo order with no matching exchange algo
    order (cancel/disappeared).
  - UNSYNCED_POSITION: exchange position with no matching local intent
    (suspicious — drives SAFE_MODE but not the sweeper).

The module is dependency-free: stdlib + `src/domain/enums.py` only.
No Binance SDK, no SQLAlchemy, no Pydantic, no Polars.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from src.domain.enums import OrderRole, OrderStatus

# --------------------------------------------------------------------------- #
# Divergence-kind vocabulary.
#
# These are the only divergence kinds the reconciler emits. The sweeper
# consumes `orphan_protectives` (a subset of `divergences`) — the only
# divergences the cancel path is authorised to act on. Other kinds
# drive SAFE_MODE without any cancel call.
# --------------------------------------------------------------------------- #

DIVERGENCE_KIND_ORPHAN_PROTECTIVE: str = "ORPHAN_PROTECTIVE"
DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE: str = "ENTRY_WITHOUT_PROTECTIVE"
DIVERGENCE_KIND_UNSYNCED_NORMAL: str = "UNSYNCED_NORMAL"
DIVERGENCE_KIND_UNSYNCED_ALGO: str = "UNSYNCED_ALGO"
DIVERGENCE_KIND_UNSYNCED_POSITION: str = "UNSYNCED_POSITION"

_DIVERGENCE_KINDS: frozenset[str] = frozenset(
    {
        DIVERGENCE_KIND_ORPHAN_PROTECTIVE,
        DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE,
        DIVERGENCE_KIND_UNSYNCED_NORMAL,
        DIVERGENCE_KIND_UNSYNCED_ALGO,
        DIVERGENCE_KIND_UNSYNCED_POSITION,
    }
)


# --------------------------------------------------------------------------- #
# Frozen dataclasses — the public compare contract.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LocalOrderIntent:
    """Lightweight carrier for one local open-order intent.

    Caller-supplied (the orchestrator translates its `Order` rows into
    these). `order_role` is the canonical `OrderRole` value; `status`
    is the local lifecycle state.
    """

    client_order_id: str
    symbol: str
    order_role: str
    status: str


@dataclass(frozen=True)
class LocalAlgoIntent:
    """Lightweight carrier for one local open-algo-order intent."""

    client_algo_id: str
    symbol: str
    order_role: str
    status: str


@dataclass(frozen=True)
class LocalPositionIntent:
    """Lightweight carrier for one local open-position intent."""

    symbol: str
    position_side: str
    position_amt: Any  # Decimal — accepted as Any to keep this layer dependency-free


@dataclass(frozen=True)
class OrphanProtective:
    """One orphan protective ready for the sweeper.

    Carries only the fields the sweeper needs to address the cancel
    call and to journal the pre/post images. The full algo snapshot
    is fetched by the sweeper via `query_algo_order_by_client` before
    the cancel — this keeps the compare pure and lets the sweeper
    verify the algo still exists (T-8-32).
    """

    symbol: str
    client_algo_id: str
    order_role: str


@dataclass(frozen=True)
class Divergence:
    """One typed divergence between local intent and exchange truth.

    `symbol` is always populated. `client_order_id` /
    `client_algo_id` are populated for the kinds that target a
    specific order. `reason` is a human-readable explanation suitable
    for log lines and journal payloads.
    """

    kind: str
    symbol: str
    order_role: str
    client_order_id: str | None
    client_algo_id: str | None
    reason: str

    def __post_init__(self) -> None:
        if self.kind not in _DIVERGENCE_KINDS:
            raise ValueError(
                f"Divergence: unknown kind {self.kind!r} "
                f"(known: {sorted(_DIVERGENCE_KINDS)})"
            )
        if not isinstance(self.symbol, str) or self.symbol == "":
            raise ValueError("Divergence: symbol must be a non-empty string")
        if not isinstance(self.order_role, str) or self.order_role == "":
            raise ValueError(
                "Divergence: order_role must be a non-empty string"
            )


@dataclass(frozen=True)
class CompareDiff:
    """Result of `compare(...)`.

    `agreement=True` iff `divergences` is empty. `orphan_protectives`
    is the subset of `divergences` the sweeper is authorised to act
    on (mirrors the ORPHAN_PROTECTIVE divergence kind). Both lists
    are sorted by `(symbol, client_algo_id or client_order_id)` for
    deterministic downstream consumption.
    """

    agreement: bool
    divergences: tuple[Divergence, ...] = field(default_factory=tuple)
    orphan_protectives: tuple[OrphanProtective, ...] = field(
        default_factory=tuple
    )


# --------------------------------------------------------------------------- #
# Public entry point.
# --------------------------------------------------------------------------- #


# Local intent statuses that should be present in the exchange truth.
# PLANNED means "intent exists locally but not yet submitted";
# SUBMITTING means "in flight"; NEW means "live on the exchange";
# PARTIALLY_FILLED means "partially live". All four must have a
# matching truth row (or the divergence is unsynced). FILLED, CANCELED,
# EXPIRED, REJECTED have NO truth row by definition and MUST NOT
# appear in local intent at compare time.
_LOCAL_OPEN_STATUSES: frozenset[str] = frozenset(
    {
        OrderStatus.PLANNED.value,
        OrderStatus.SUBMITTING.value,
        OrderStatus.NEW.value,
        OrderStatus.PARTIALLY_FILLED.value,
    }
)


def compare(
    *,
    local_open_orders: Sequence[Any],
    local_open_algos: Sequence[Any],
    local_open_positions: Sequence[Any],
    truth_normal_orders: Sequence[Any],
    truth_algo_orders: Sequence[Any],
    truth_positions: Sequence[Any],
) -> CompareDiff:
    """Three-source set-difference compare.

    Args:
        local_open_orders: Sequence of `LocalOrderIntent` (or duck-
            typed equivalents with `client_order_id`, `symbol`,
            `order_role`, `status` attributes).
        local_open_algos: Sequence of `LocalAlgoIntent`.
        local_open_positions: Sequence of `LocalPositionIntent`.
        truth_normal_orders: Sequence of `OpenOrderSnapshot`.
        truth_algo_orders: Sequence of `OpenAlgoOrderSnapshot`.
        truth_positions: Sequence of `PositionSnapshot`.

    Returns:
        A `CompareDiff` carrying `agreement`, the full `divergences`
        list, and the `orphan_protectives` subset the sweeper is
        authorised to act on.

    Note:
        The function is pure — it does not call the adapter. The
        caller (the scheduled reconciler tick) is responsible for
        fetching the three truth snapshots before invoking compare.
    """
    divergences: list[Divergence] = []

    # Index truth rows by their canonical identifier for O(1) lookup.
    truth_normal_by_client_id: dict[str, Any] = {
        o.client_order_id: o for o in truth_normal_orders
    }
    truth_algo_by_client_id: dict[str, Any] = {
        o.client_algo_id: o for o in truth_algo_orders
    }

    # Index local intent by canonical identifier for the reverse check.
    local_normal_by_client_id: dict[str, Any] = {}
    for entry in local_open_orders:
        if not _is_local_intent_open(entry):
            continue
        client_order_id = _get_field(entry, "client_order_id")
        if client_order_id is None:
            raise ValueError(
                f"local order intent missing client_order_id: {entry!r}"
            )
        local_normal_by_client_id[client_order_id] = entry

    local_algo_by_client_id: dict[str, Any] = {}
    for entry in local_open_algos:
        if not _is_local_intent_open(entry):
            continue
        client_algo_id = _get_field(entry, "client_algo_id")
        if client_algo_id is None:
            raise ValueError(
                f"local algo intent missing client_algo_id: {entry!r}"
            )
        local_algo_by_client_id[client_algo_id] = entry

    local_position_keys: set[tuple[str, str]] = {
        (
            _get_field(p, "symbol"),
            _get_field(p, "position_side"),
        )
        for p in local_open_positions
    }

    # Pass 1 — for each local algo intent, classify it.
    for algo_intent in local_algo_by_client_id.values():
        client_algo_id = _get_field(algo_intent, "client_algo_id")
        symbol = _get_field(algo_intent, "symbol")
        order_role = _get_field(algo_intent, "order_role")
        is_protective = _is_protective_role(order_role)

        # Determine whether any position exists for this symbol
        # (local or exchange). A protective with no position is an
        # orphan protective regardless of whether the algo itself
        # still matches the exchange truth — the algo is supposed
        # to protect a position, and there is no position to
        # protect.
        has_local_position = any(k[0] == symbol for k in local_position_keys)
        has_exchange_position = any(p.symbol == symbol for p in truth_positions)
        has_position = has_local_position or has_exchange_position

        if is_protective and not has_position:
            # Orphan protective: the algo still exists in local
            # intent but there is no position to protect. The
            # sweeper's authoritative position-zero verification is
            # the next gate before the cancel call.
            divergences.append(
                Divergence(
                    kind=DIVERGENCE_KIND_ORPHAN_PROTECTIVE,
                    symbol=symbol,
                    order_role=order_role,
                    client_order_id=None,
                    client_algo_id=client_algo_id,
                    reason=(
                        "local algo protective with no matching local "
                        "position and no exchange position"
                    ),
                )
            )
            continue

        truth_algo = truth_algo_by_client_id.get(client_algo_id)
        if truth_algo is None:
            # Local algo with no matching exchange algo (non-orphan).
            divergences.append(
                Divergence(
                    kind=DIVERGENCE_KIND_UNSYNCED_ALGO,
                    symbol=symbol,
                    order_role=order_role,
                    client_order_id=None,
                    client_algo_id=client_algo_id,
                    reason=(
                        "local algo with no matching exchange algo"
                    ),
                )
            )

    # Pass 2 — for each local normal order intent, classify it.
    for order_intent in local_normal_by_client_id.values():
        client_order_id = _get_field(order_intent, "client_order_id")
        symbol = _get_field(order_intent, "symbol")
        order_role = _get_field(order_intent, "order_role")
        truth_normal = truth_normal_by_client_id.get(client_order_id)
        if truth_normal is None:
            divergences.append(
                Divergence(
                    kind=DIVERGENCE_KIND_UNSYNCED_NORMAL,
                    symbol=symbol,
                    order_role=order_role,
                    client_order_id=client_order_id,
                    client_algo_id=None,
                    reason=(
                        "local normal order with no matching exchange "
                        "order (cancel or external fill?)"
                    ),
                )
            )
            continue

        # ENTRY_WITHOUT_PROTECTIVE: a local ENTRY with no matching
        # algo protective for the same symbol. This drives SAFE_MODE
        # but the sweeper never places rescue protection (Pitfall 1).
        if order_role == OrderRole.ENTRY.value:
            has_protective = any(
                _get_field(a, "symbol") == symbol
                and _is_protective_role(_get_field(a, "order_role"))
                for a in local_algo_by_client_id.values()
            )
            if not has_protective:
                divergences.append(
                    Divergence(
                        kind=DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE,
                        symbol=symbol,
                        order_role=order_role,
                        client_order_id=client_order_id,
                        client_algo_id=None,
                        reason=(
                            "local ENTRY with no matching algo protective "
                            "for the same symbol"
                        ),
                    )
                )

    # Pass 3 — for each exchange position, check it has a local match.
    for truth_pos in truth_positions:
        key = (truth_pos.symbol, truth_pos.position_side)
        if key not in local_position_keys:
            divergences.append(
                Divergence(
                    kind=DIVERGENCE_KIND_UNSYNCED_POSITION,
                    symbol=truth_pos.symbol,
                    order_role="N/A",
                    client_order_id=None,
                    client_algo_id=None,
                    reason=(
                        "exchange position with no matching local intent"
                    ),
                )
            )

    # Sort divergences deterministically.
    divergences.sort(
        key=lambda d: (
            d.symbol,
            d.client_algo_id or "",
            d.client_order_id or "",
            d.kind,
        )
    )

    orphan_protectives = tuple(
        OrphanProtective(
            symbol=d.symbol,
            client_algo_id=d.client_algo_id or "",
            order_role=d.order_role,
        )
        for d in divergences
        if d.kind == DIVERGENCE_KIND_ORPHAN_PROTECTIVE
    )

    return CompareDiff(
        agreement=len(divergences) == 0,
        divergences=tuple(divergences),
        orphan_protectives=orphan_protectives,
    )


# --------------------------------------------------------------------------- #
# Internal helpers.
# --------------------------------------------------------------------------- #


_PROTECTIVE_ROLES: frozenset[str] = frozenset(
    {
        OrderRole.STOP_LOSS.value,
        OrderRole.TAKE_PROFIT_1.value,
        OrderRole.TAKE_PROFIT_2.value,
    }
)


def _is_protective_role(order_role: str) -> bool:
    """True when the order role is a protective (SL / TP1 / TP2).

    ENTRY is not a protective — an entry without protection is
    UNSYNCED_NORMAL (drives SAFE_MODE but not the sweeper), while a
    protective without a position is ORPHAN_PROTECTIVE (the sweeper's
    target).
    """
    return order_role in _PROTECTIVE_ROLES


def _is_local_intent_open(entry: Any) -> bool:
    """True when the local intent's status is one of PLANNED/SUBMITTING/NEW/PARTIALLY_FILLED.

    Other statuses (FILLED/CANCELED/EXPIRED/REJECTED) MUST NOT appear
    in local intent at compare time — if they do, the caller has a
    stale row that the compare layer surfaces as a divergence rather
    than silently ignoring.

    Accepts both attribute-style objects (the canonical
    `LocalOrderIntent` / `LocalAlgoIntent` dataclasses) and dict-style
    payloads (the test fixture format). The duck-typed lookup is
    intentional — the compare layer is the boundary between the
    orchestrator's local-intent representation and the exchange-truth
    snapshots.
    """
    status = _get_field(entry, "status")
    if status is None:
        raise ValueError(
            f"local intent missing status attribute: {entry!r}"
        )
    return status in _LOCAL_OPEN_STATUSES


def _get_field(entry: Any, field_name: str) -> Any:
    """Read a field from either an object (attribute) or a dict (key)."""
    if isinstance(entry, dict):
        return entry.get(field_name)
    return getattr(entry, field_name, None)


def _symbols_for_position_side(
    local_position_keys: set[tuple[str, str]], symbol: str
) -> set[tuple[str, str]]:
    """Return the subset of `local_position_keys` for one symbol."""
    return {k for k in local_position_keys if k[0] == symbol}


__all__ = [
    "compare",
    "CompareDiff",
    "Divergence",
    "LocalOrderIntent",
    "LocalAlgoIntent",
    "LocalPositionIntent",
    "OrphanProtective",
    "DIVERGENCE_KIND_ORPHAN_PROTECTIVE",
    "DIVERGENCE_KIND_UNSYNCED_NORMAL",
    "DIVERGENCE_KIND_UNSYNCED_ALGO",
    "DIVERGENCE_KIND_UNSYNCED_POSITION",
]
