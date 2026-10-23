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
    order (cancel/disappeared). One exception (plan 20-28, WR-B2): the TP1 leg of a COMPLETE plan
    carries `explained_when_position_below`, and its absence is not a divergence while exactly one
    exchange position of the plan's side exists and is strictly below that quantity (a TP1 that
    triggered and filled leaves the open algo orders).
  - UNSYNCED_POSITION: exchange position with no matching local intent
    (suspicious — drives SAFE_MODE but not the sweeper).

Phase 20 (plan 20-04) adds, without changing the five above:

  - FOREIGN_ORDER: an exchange order with no local intent whose id does not
    carry this system's prefix. Never sweepable, never cancelled (D-02).
  - UNTRACKED_SYSTEM_ORDER: an exchange order with no local intent whose id
    does carry this system's prefix. Still a divergence, still not sweepable.
  - DUPLICATE_EXCHANGE_ID: the same client id twice in the exchange truth.
  - DOUBLED_POSITION / SIGN_FLIPPED_POSITION: the signed bound check.
  - POSITION_WITHOUT_STOP / TP_ONLY_POSITION: no ACTIVE system STOP_LOSS.
  - AMBIGUOUS_POSITION_OWNER: exposure that cannot be tied to one plan.
  - UNSUPPORTED_POSITION_SIDE: a Hedge-mode row (V1 is One-way only).
  - STREAM_SINK_FAILURE / STREAM_TASK_DIED: vocabulary for plan 20-16; this
    module emits neither.

Phase 20 (plan 20-20, owner decision O-D, not D-13) adds one optional local input,
`local_active_plans`: more than one distinct active plan for one symbol is also
AMBIGUOUS_POSITION_OWNER, with or without exchange exposure. The compare never picks one
of the plans.

The module is dependency-free: stdlib, `src/domain` and the pure id
predicates of `src/execution/order_ids.py`. No Binance SDK, no SQLAlchemy,
no Pydantic, no Polars.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from src.domain.algo_status import is_protection_confirmed
from src.domain.enums import OrderRole, OrderStatus
from src.execution.order_ids import (
    is_system_client_id,
    plan_hash_prefix_of,
    role_of_client_id,
)

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

# Phase 20 (plan 20-04, D-01..D-04, D-07).
DIVERGENCE_KIND_FOREIGN_ORDER: str = "FOREIGN_ORDER"
DIVERGENCE_KIND_UNTRACKED_SYSTEM_ORDER: str = "UNTRACKED_SYSTEM_ORDER"
DIVERGENCE_KIND_DUPLICATE_EXCHANGE_ID: str = "DUPLICATE_EXCHANGE_ID"
DIVERGENCE_KIND_DOUBLED_POSITION: str = "DOUBLED_POSITION"
DIVERGENCE_KIND_SIGN_FLIPPED_POSITION: str = "SIGN_FLIPPED_POSITION"
DIVERGENCE_KIND_TP_ONLY_POSITION: str = "TP_ONLY_POSITION"
DIVERGENCE_KIND_POSITION_WITHOUT_STOP: str = "POSITION_WITHOUT_STOP"
DIVERGENCE_KIND_AMBIGUOUS_POSITION_OWNER: str = "AMBIGUOUS_POSITION_OWNER"
DIVERGENCE_KIND_UNSUPPORTED_POSITION_SIDE: str = "UNSUPPORTED_POSITION_SIDE"
# Vocabulary only: plan 20-16 emits these two (D-04). This module never does.
DIVERGENCE_KIND_STREAM_SINK_FAILURE: str = "STREAM_SINK_FAILURE"
DIVERGENCE_KIND_STREAM_TASK_DIED: str = "STREAM_TASK_DIED"

_DIVERGENCE_KINDS: frozenset[str] = frozenset(
    {
        DIVERGENCE_KIND_ORPHAN_PROTECTIVE,
        DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE,
        DIVERGENCE_KIND_UNSYNCED_NORMAL,
        DIVERGENCE_KIND_UNSYNCED_ALGO,
        DIVERGENCE_KIND_UNSYNCED_POSITION,
        DIVERGENCE_KIND_FOREIGN_ORDER,
        DIVERGENCE_KIND_UNTRACKED_SYSTEM_ORDER,
        DIVERGENCE_KIND_DUPLICATE_EXCHANGE_ID,
        DIVERGENCE_KIND_DOUBLED_POSITION,
        DIVERGENCE_KIND_SIGN_FLIPPED_POSITION,
        DIVERGENCE_KIND_TP_ONLY_POSITION,
        DIVERGENCE_KIND_POSITION_WITHOUT_STOP,
        DIVERGENCE_KIND_AMBIGUOUS_POSITION_OWNER,
        DIVERGENCE_KIND_UNSUPPORTED_POSITION_SIDE,
        DIVERGENCE_KIND_STREAM_SINK_FAILURE,
        DIVERGENCE_KIND_STREAM_TASK_DIED,
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
    # Phase 20: the plan this order belongs to (64-char hash). Optional; when absent the
    # compare falls back to the plan-hash prefix inside the client id.
    plan_hash: str | None = None


@dataclass(frozen=True)
class LocalAlgoIntent:
    """Lightweight carrier for one local open-algo-order intent.

    `explained_when_position_below` (plan 20-28, WR-B2) is set only for the TP1 leg of a plan in
    state COMPLETE: the intended quantity of the plan. A TP1 that triggers and fills leaves the
    exchange's open algo orders (Binance Demo: TRIGGERING, TRIGGERED, FINISHED), so its absence is
    explained when exactly one exchange position of the plan's side exists and its absolute amount
    is strictly below this bound. None (the default) means the leg's absence is always a
    divergence.
    """

    client_algo_id: str
    symbol: str
    order_role: str
    status: str
    plan_hash: str | None = None
    explained_when_position_below: Any = None  # Decimal: the plan's intended quantity


@dataclass(frozen=True)
class LocalPositionIntent:
    """Lightweight carrier for one local open-position intent."""

    symbol: str
    position_side: str
    position_amt: Any  # Decimal — accepted as Any to keep this layer dependency-free
    # Phase 20 (D-01a): what the compare needs to check the exchange amount against the plan.
    # All three default to None so older fixtures stay constructible; a position whose intent
    # lacks any of them cannot be attributed to a plan with a checkable side and bound, so
    # the compare reports AMBIGUOUS_POSITION_OWNER and never an agreement.
    plan_hash: str | None = None
    expected_side: str | None = None  # "LONG" / "SHORT": the side of the owning plan
    max_abs_amount: Any = None  # Decimal: the intended quantity, the upper bound of abs(exchange)


@dataclass(frozen=True)
class LocalActivePlan:
    """One plan that is active locally: it may still place, hold or close exposure on `symbol`.

    Phase 20 (plan 20-20, owner decision O-D). Evidence of ownership only; Binance stays the
    authority for positions and orders.
    """

    plan_hash: str
    symbol: str


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
                f"Divergence: unknown kind {self.kind!r} (known: {sorted(_DIVERGENCE_KINDS)})"
            )
        if not isinstance(self.symbol, str) or self.symbol == "":
            raise ValueError("Divergence: symbol must be a non-empty string")
        if not isinstance(self.order_role, str) or self.order_role == "":
            raise ValueError("Divergence: order_role must be a non-empty string")


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
    orphan_protectives: tuple[OrphanProtective, ...] = field(default_factory=tuple)


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
    local_active_plans: Sequence[Any] = (),
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
        local_active_plans: Optional sequence of `LocalActivePlan` (or duck-typed items
            with `plan_hash` and `symbol`): the plans that are active locally. A symbol
            with more than one distinct `plan_hash` yields one AMBIGUOUS_POSITION_OWNER
            (merged with the exposure-based emission, so a symbol never yields two); an
            item whose plan hash or symbol is missing cannot be attributed and also yields
            one. Default empty: existing callers are unchanged.

    Returns:
        A `CompareDiff` carrying `agreement`, the full `divergences`
        list, and the `orphan_protectives` subset the sweeper is
        authorised to act on.

    Raises:
        TypeError: any of the seven sources is None (a missing source is never
            read as empty), or an exchange `position_amt` is not a `Decimal`.
        ValueError: an exchange `position_amt` is not finite.

    Note:
        The function is pure — it does not call the adapter. The
        caller (the scheduled reconciler tick) is responsible for
        fetching the three truth snapshots before invoking compare.

        Signed amount is a BOUND check per symbol (Phase 20, D-01a), not an
        exact reconciliation: the sign of the exchange amount must match the
        side of the owning plan (LONG needs a positive amount, SHORT a
        negative one) and `abs(exchange amount)` must not exceed the plan's
        intended quantity (equality agrees). When both the sign and the bound
        are violated only SIGN_FLIPPED_POSITION is reported (sign is checked
        first). An over-fill that stays below the intended quantity is NOT
        detectable here; exact comparison needs the fills ledger and Order
        rows attributed by client order id (Phase 24, D-13 deferred). A
        One-way position is the symbol's total exposure, so the check is per
        symbol; it equals a per-plan check only while the Phase 19
        one-plan-per-symbol pre-placement rule holds. Two plans on one symbol,
        or exposure whose owner cannot be determined (missing plan_hash,
        expected_side or a positive Decimal max_abs_amount), is
        AMBIGUOUS_POSITION_OWNER; the compare never picks one plan. The same kind
        is emitted, without any exposure, when `local_active_plans` shows more than one
        distinct plan for one symbol (plan 20-20, owner decision O-D): the premise of the
        per-symbol bound check is broken even before a fill.

        The compare holds no clock and cannot judge the age of its inputs.
        Stale or unreadable local data must be refused by the caller before
        compare is invoked (plans 20-12 and 20-20), never passed as empty.
    """
    _require_sources(
        local_open_orders=local_open_orders,
        local_open_algos=local_open_algos,
        local_open_positions=local_open_positions,
        truth_normal_orders=truth_normal_orders,
        truth_algo_orders=truth_algo_orders,
        truth_positions=truth_positions,
        local_active_plans=local_active_plans,
    )
    for _row in truth_positions:
        _require_decimal_amount(_row)

    divergences: list[Divergence] = []

    # Index truth rows by their canonical identifier for O(1) lookup. A repeated id
    # is a divergence (D-03), not a silent last-row-wins collapse; the first row is kept.
    truth_normal_by_client_id: dict[str, Any] = {}
    for _order in truth_normal_orders:
        _oid = _get_field(_order, "client_order_id")
        if not isinstance(_oid, str) or _oid == "":
            continue
        if _oid in truth_normal_by_client_id:
            if not any(d.client_order_id == _oid for d in divergences):
                divergences.append(_duplicate_id_divergence(truth_normal_by_client_id[_oid], _oid))
            continue
        truth_normal_by_client_id[_oid] = _order
    truth_algo_by_client_id: dict[str, Any] = {}
    for _algo in truth_algo_orders:
        _aid = _get_field(_algo, "client_algo_id")
        if not isinstance(_aid, str) or _aid == "":
            continue
        if _aid in truth_algo_by_client_id:
            if not any(d.client_algo_id == _aid for d in divergences):
                divergences.append(
                    _duplicate_id_divergence(truth_algo_by_client_id[_aid], _aid, is_algo=True)
                )
            continue
        truth_algo_by_client_id[_aid] = _algo

    # Index local intent by canonical identifier for the reverse check.
    local_normal_by_client_id: dict[str, Any] = {}
    for entry in local_open_orders:
        try:
            is_open = _is_local_intent_open(entry)
        except ValueError:
            is_open = True
        if not is_open:
            continue
        client_order_id = _get_field(entry, "client_order_id")
        if not isinstance(client_order_id, str) or client_order_id == "":
            _sym = _get_field(entry, "symbol")
            divergences.append(
                Divergence(
                    kind=DIVERGENCE_KIND_UNSYNCED_NORMAL,
                    symbol=_sym if isinstance(_sym, str) and _sym else "UNKNOWN",
                    order_role=_get_field(entry, "order_role") or "UNKNOWN",
                    client_order_id=None,
                    client_algo_id=None,
                    reason="local intent missing identity field",
                )
            )
            continue
        local_normal_by_client_id[client_order_id] = entry

    local_algo_by_client_id: dict[str, Any] = {}
    for entry in local_open_algos:
        try:
            is_open = _is_local_intent_open(entry)
        except ValueError:
            is_open = True
        if not is_open:
            continue
        client_algo_id = _get_field(entry, "client_algo_id")
        if not isinstance(client_algo_id, str) or client_algo_id == "":
            _sym = _get_field(entry, "symbol")
            divergences.append(
                Divergence(
                    kind=DIVERGENCE_KIND_UNSYNCED_ALGO,
                    symbol=_sym if isinstance(_sym, str) and _sym else "UNKNOWN",
                    order_role=_get_field(entry, "order_role") or "UNKNOWN",
                    client_order_id=None,
                    client_algo_id=None,
                    reason="local intent missing identity field",
                )
            )
            continue
        local_algo_by_client_id[client_algo_id] = entry

    local_position_keys: set[tuple[str, Any]] = set()
    for p in local_open_positions:
        if _is_zero_like(_get_field(p, "position_amt")):
            continue
        _sym = _get_field(p, "symbol")
        if not isinstance(_sym, str) or _sym == "":
            continue
        local_position_keys.add((_sym, _get_field(p, "position_side")))

    # Plans whose ENTRY is still resting or partially filled (D-05 code part): locally NEW /
    # PARTIALLY_FILLED, or still among the exchange open normal orders. Since Phase 19 the
    # stop is placed after the first fill, so a protective of such a plan is not an orphan.
    resting_entry_plans: set[str] = set()
    for entry in local_normal_by_client_id.values():
        if (
            _get_field(entry, "order_role") == OrderRole.ENTRY.value
            and _get_field(entry, "status") in _RESTING_ENTRY_STATUSES
        ):
            entry_key = _plan_key(entry, "client_order_id")
            if entry_key is not None:
                resting_entry_plans.add(entry_key)
    for truth_entry_id in truth_normal_by_client_id:
        if role_of_client_id(truth_entry_id) == OrderRole.ENTRY.value:
            truth_key = plan_hash_prefix_of(truth_entry_id)
            if truth_key is not None:
                resting_entry_plans.add(truth_key)

    # Pass 1 — for each local algo intent, classify it.
    for algo_intent in local_algo_by_client_id.values():
        client_algo_id = _get_field(algo_intent, "client_algo_id")
        symbol = _get_field(algo_intent, "symbol")
        order_role = _get_field(algo_intent, "order_role")
        is_protective = _is_protective_role(order_role)
        algo_side = _get_field(algo_intent, "position_side")

        if algo_side:
            has_local_position = (symbol, algo_side) in local_position_keys
        else:
            has_local_position = any(k[0] == symbol for k in local_position_keys)
        has_exchange_position = any(
            _get_field(p, "symbol") == symbol
            and (not algo_side or _get_field(p, "position_side") == algo_side)
            and not _is_zero_like(_get_field(p, "position_amt"))
            for p in truth_positions
        )
        has_position = has_local_position or has_exchange_position

        entry_is_resting = _plan_key(algo_intent, "client_algo_id") in resting_entry_plans
        if is_protective and not has_position and not entry_is_resting:
            if truth_algo_by_client_id.get(client_algo_id) is None:
                divergences.append(
                    Divergence(
                        kind=DIVERGENCE_KIND_UNSYNCED_ALGO,
                        symbol=symbol,
                        order_role=order_role,
                        client_order_id=None,
                        client_algo_id=client_algo_id,
                        reason=(
                            "local algo protective with no matching "
                            "exchange algo and no position to protect"
                        ),
                    )
                )
                continue
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
            if _leg_absence_explained(algo_intent, local_open_positions, truth_positions):
                # A TP1 that triggered and filled (plan 20-28, WR-B2): not a divergence.
                continue
            # Local algo with no matching exchange algo (non-orphan).
            divergences.append(
                Divergence(
                    kind=DIVERGENCE_KIND_UNSYNCED_ALGO,
                    symbol=symbol,
                    order_role=order_role,
                    client_order_id=None,
                    client_algo_id=client_algo_id,
                    reason=("local algo with no matching exchange algo"),
                )
            )

    # Pass 1b — for each local position intent with non-zero amount,
    # require at least one open protective (local algo intent in an
    # open status) for the same symbol. A filled ENTRY leaves local
    # intent as a position row only, so a position with zero
    # protective algos must diverge — never read as clean.
    for local_pos in local_open_positions:
        position_amt = _get_field(local_pos, "position_amt")
        if _is_zero_like(position_amt):
            continue
        pos_symbol = _get_field(local_pos, "symbol")
        if not isinstance(pos_symbol, str) or pos_symbol == "":
            divergences.append(
                Divergence(
                    kind=DIVERGENCE_KIND_UNSYNCED_POSITION,
                    symbol="UNKNOWN",
                    order_role="POSITION",
                    client_order_id=None,
                    client_algo_id=None,
                    reason="local position intent missing symbol",
                )
            )
            continue
        pos_side = _get_field(local_pos, "position_side")
        has_protective = any(
            _get_field(a, "symbol") == pos_symbol
            and _is_protective_role(_get_field(a, "order_role"))
            and (
                not pos_side
                or not _get_field(a, "position_side")
                or _get_field(a, "position_side") == pos_side
            )
            for a in local_algo_by_client_id.values()
        )
        if not has_protective:
            divergences.append(
                Divergence(
                    kind=DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE,
                    symbol=pos_symbol,
                    order_role=pos_side if isinstance(pos_side, str) and pos_side else "POSITION",
                    client_order_id=None,
                    client_algo_id=None,
                    reason=("local position with no protective algo for the same symbol"),
                )
            )

    # Pass 2 — for each local normal order intent, classify it.
    for order_intent in local_normal_by_client_id.values():
        client_order_id = _get_field(order_intent, "client_order_id")
        symbol = _get_field(order_intent, "symbol")
        order_role = _get_field(order_intent, "order_role")
        truth_normal = truth_normal_by_client_id.get(client_order_id)

        if order_role == OrderRole.ENTRY.value:
            has_protective = any(
                _get_field(a, "symbol") == symbol
                and _is_protective_role(_get_field(a, "order_role"))
                and _get_field(a, "client_algo_id") in truth_algo_by_client_id
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
                        reason=("local ENTRY with no matching algo protective for the same symbol"),
                    )
                )

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

    # Pass 3 — for each exchange position: Hedge refusal, local match, ownership and the
    # signed bound check (D-01a), and the STOP requirement (D-01, D-07).
    for truth_pos in truth_positions:
        amount = _get_field(truth_pos, "position_amt")
        if amount == 0:
            continue
        pos_side = _get_field(truth_pos, "position_side")
        raw_symbol = _get_field(truth_pos, "symbol")
        symbol_text = raw_symbol if isinstance(raw_symbol, str) and raw_symbol else "UNKNOWN"
        if pos_side in _HEDGE_POSITION_SIDES:
            divergences.append(
                Divergence(
                    kind=DIVERGENCE_KIND_UNSUPPORTED_POSITION_SIDE,
                    symbol=symbol_text,
                    order_role=pos_side,
                    client_order_id=None,
                    client_algo_id=None,
                    reason="Hedge-mode position row (V1 supports One-way only)",
                )
            )
            continue
        if (raw_symbol, pos_side) not in local_position_keys:
            divergences.append(
                Divergence(
                    kind=DIVERGENCE_KIND_UNSYNCED_POSITION,
                    symbol=raw_symbol,
                    order_role="N/A",
                    client_order_id=None,
                    client_algo_id=None,
                    reason=("exchange position with no matching local intent"),
                )
            )
        else:
            local_for_symbol = [
                p
                for p in local_open_positions
                if _get_field(p, "symbol") == raw_symbol
                and not _is_zero_like(_get_field(p, "position_amt"))
            ]
            owner_kind, owner_reason = _check_position_bound(amount, local_for_symbol)
            if owner_kind is not None:
                divergences.append(
                    Divergence(
                        kind=owner_kind,
                        symbol=symbol_text,
                        order_role="POSITION",
                        client_order_id=None,
                        client_algo_id=None,
                        reason=owner_reason,
                    )
                )
        stop_kind = _check_stop(raw_symbol, truth_algo_orders)
        if stop_kind is not None:
            divergences.append(
                Divergence(
                    kind=stop_kind,
                    symbol=symbol_text,
                    order_role="POSITION",
                    client_order_id=None,
                    client_algo_id=None,
                    reason=(
                        "exchange position with only take-profit legs and no STOP_LOSS"
                        if stop_kind == DIVERGENCE_KIND_TP_ONLY_POSITION
                        else "exchange position without an ACTIVE system STOP_LOSS algo order"
                    ),
                )
            )

    # Pass 3b — symbol ownership (plan 20-20, owner decision O-D): more than one active plan
    # for one symbol, or an active plan that cannot be named, is AMBIGUOUS_POSITION_OWNER. A
    # symbol that Pass 3 already reported is not reported twice. Nothing here picks a plan.
    already_ambiguous = {
        d.symbol for d in divergences if d.kind == DIVERGENCE_KIND_AMBIGUOUS_POSITION_OWNER
    }
    for conflict_symbol, conflict_reason in _ownership_conflicts(local_active_plans):
        if conflict_symbol in already_ambiguous:
            continue
        already_ambiguous.add(conflict_symbol)
        divergences.append(
            Divergence(
                kind=DIVERGENCE_KIND_AMBIGUOUS_POSITION_OWNER,
                symbol=conflict_symbol,
                order_role="POSITION",
                client_order_id=None,
                client_algo_id=None,
                reason=conflict_reason,
            )
        )

    # Pass 4 — reverse pass (D-01, D-02): every exchange order with no open local
    # intent is a divergence. A foreign order is never added to `orphan_protectives`.
    reported_ids: set[str] = set()
    for truth_order in truth_normal_orders:
        order_id = _get_field(truth_order, "client_order_id")
        if isinstance(order_id, str) and order_id != "":
            if order_id in local_normal_by_client_id or order_id in reported_ids:
                continue
            reported_ids.add(order_id)
        divergences.append(_unowned_order_divergence(truth_order, order_id, is_algo=False))
    for truth_algo in truth_algo_orders:
        algo_id = _get_field(truth_algo, "client_algo_id")
        if isinstance(algo_id, str) and algo_id != "":
            if algo_id in local_algo_by_client_id or algo_id in reported_ids:
                continue
            reported_ids.add(algo_id)
        divergences.append(_unowned_order_divergence(truth_algo, algo_id, is_algo=True))

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


def _is_zero_like(value: Any) -> bool:
    if value is None:
        return False
    try:
        return bool(value == 0)
    except TypeError:
        return False


def _leg_absence_explained(
    algo_intent: Any, local_open_positions: Sequence[Any], truth_positions: Sequence[Any]
) -> bool:
    """True when a missing algo leg is explained by a fill that reduced the position (WR-B2).

    Only a leg that carries `explained_when_position_below` (the TP1 of a COMPLETE plan) can be
    explained, and only by evidence that the position really shrank: exactly one local position
    intent of the same plan for the symbol, exactly one non-zero exchange position row for the
    symbol on the plan's side (LONG positive, SHORT negative) and `0 < abs(amount) < bound`. A
    full or larger position, no position, a second plan, a second row, the wrong side or a bound
    that is not a positive Decimal all keep the divergence. The stop and TP2 never carry the bound.
    """
    bound = _get_field(algo_intent, "explained_when_position_below")
    if not _is_positive_decimal(bound):
        return False
    plan_hash = _get_field(algo_intent, "plan_hash")
    symbol = _get_field(algo_intent, "symbol")
    if not isinstance(plan_hash, str) or plan_hash == "" or not isinstance(symbol, str):
        return False
    local_rows = [p for p in local_open_positions if _get_field(p, "symbol") == symbol]
    if len(local_rows) != 1 or _get_field(local_rows[0], "plan_hash") != plan_hash:
        return False
    side = _get_field(local_rows[0], "expected_side")
    exchange_rows = [
        p
        for p in truth_positions
        if _get_field(p, "symbol") == symbol and _get_field(p, "position_amt") != 0
    ]
    if len(exchange_rows) != 1:
        return False
    amount = _get_field(exchange_rows[0], "position_amt")
    if not isinstance(amount, Decimal) or not amount.is_finite():
        return False
    if (side == "LONG" and amount > 0) or (side == "SHORT" and amount < 0):
        return bool(abs(amount) < bound)
    return False


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
        raise ValueError(f"local intent missing status attribute: {entry!r}")
    return status in _LOCAL_OPEN_STATUSES


def _get_field(entry: Any, field_name: str) -> Any:
    """Read a field from either an object (attribute) or a dict (key)."""
    if isinstance(entry, dict):
        return entry.get(field_name)
    return getattr(entry, field_name, None)


_HEDGE_POSITION_SIDES: frozenset[str] = frozenset({"LONG", "SHORT"})

# A local ENTRY in one of these states can still fill, so its plan's protective is not an
# orphan. PLANNED / SUBMITTING are deliberately not listed: the exemption only narrows what
# the sweeper may cancel, so it stays as small as the plan states it.
_RESTING_ENTRY_STATUSES: frozenset[str] = frozenset(
    {OrderStatus.NEW.value, OrderStatus.PARTIALLY_FILLED.value}
)


def _plan_key(intent: Any, id_field: str) -> str | None:
    """The 29-character plan key of a local intent: its plan_hash when carried, else the id's."""
    plan_hash = _get_field(intent, "plan_hash")
    if isinstance(plan_hash, str) and plan_hash != "":
        return plan_hash[:29]
    return plan_hash_prefix_of(_get_field(intent, id_field))


def _require_sources(**sources: Any) -> None:
    """Refuse a None source: a missing source is never read as an empty one."""
    for name, value in sources.items():
        if value is None:
            raise TypeError(
                f"compare: {name} must be a sequence, got None "
                "(a missing source is never read as empty)"
            )


def _require_decimal_amount(truth_pos: Any) -> None:
    amount = _get_field(truth_pos, "position_amt")
    if not isinstance(amount, Decimal):
        raise TypeError(
            f"compare: exchange position_amt must be a Decimal, got {type(amount).__name__}"
        )
    if not amount.is_finite():
        raise ValueError("compare: exchange position_amt must be finite")


def _is_positive_decimal(value: Any) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and value > 0


def _check_position_bound(
    amount: Decimal, local_for_symbol: Sequence[Any]
) -> tuple[str | None, str]:
    """Attribute exposure to one plan, then run the sign check before the bound check.

    Returns `(kind, reason)`; `kind` is None when the exposure agrees with its owner.
    """
    owners: set[tuple[str, str, Decimal]] = set()
    for intent in local_for_symbol:
        plan_hash = _get_field(intent, "plan_hash")
        side = _get_field(intent, "expected_side")
        bound = _get_field(intent, "max_abs_amount")
        if (
            not isinstance(plan_hash, str)
            or plan_hash == ""
            or side not in _HEDGE_POSITION_SIDES
            or not _is_positive_decimal(bound)
        ):
            return (
                DIVERGENCE_KIND_AMBIGUOUS_POSITION_OWNER,
                "exposure cannot be attributed to one plan with a checkable side and bound "
                "(local position intent lacks plan_hash, expected_side or a positive "
                "Decimal max_abs_amount)",
            )
        owners.add((plan_hash, side, bound))
    if len(owners) != 1:
        return (
            DIVERGENCE_KIND_AMBIGUOUS_POSITION_OWNER,
            "more than one owning plan, or conflicting plan data, for one symbol "
            "(the compare never picks one plan)",
        )
    _plan, side, bound = next(iter(owners))
    if (side == "LONG" and amount < 0) or (side == "SHORT" and amount > 0):
        return (
            DIVERGENCE_KIND_SIGN_FLIPPED_POSITION,
            f"exchange amount sign disagrees with the {side} plan",
        )
    if abs(amount) > bound:
        return (
            DIVERGENCE_KIND_DOUBLED_POSITION,
            "abs(exchange amount) is larger than the intended quantity of the plan",
        )
    return (None, "")


def _ownership_conflicts(local_active_plans: Sequence[Any]) -> list[tuple[str, str]]:
    """The `(symbol, reason)` of every symbol whose active plans cannot be told to be one.

    Fail closed: an item with no usable plan hash or symbol is a conflict of its symbol
    (`UNKNOWN` when the symbol is unusable), never silently dropped.
    """
    plans_by_symbol: dict[str, set[str]] = {}
    conflicts: dict[str, str] = {}
    for item in local_active_plans:
        plan_hash = _get_field(item, "plan_hash")
        symbol = _get_field(item, "symbol")
        usable_symbol = symbol if isinstance(symbol, str) and symbol != "" else "UNKNOWN"
        if not isinstance(plan_hash, str) or plan_hash == "" or usable_symbol == "UNKNOWN":
            conflicts.setdefault(
                usable_symbol,
                "an active local plan has no usable plan hash or symbol "
                "(ownership cannot be established; the compare never guesses)",
            )
            continue
        plans_by_symbol.setdefault(usable_symbol, set()).add(plan_hash)
    for symbol_name, hashes in plans_by_symbol.items():
        if len(hashes) > 1:
            conflicts.setdefault(
                symbol_name,
                "more than one active plan for one symbol (the compare never picks one plan)",
            )
    return sorted(conflicts.items())


def _check_stop(symbol: Any, truth_algo_orders: Sequence[Any]) -> str | None:
    """None when an ACTIVE system STOP_LOSS exists; else the kind of the missing stop.

    TP_ONLY_POSITION when there is no STOP_LOSS row of this system at all but at least one
    take-profit leg; POSITION_WITHOUT_STOP otherwise (no algo, a foreign stop, or a system
    stop whose status is not in the ACTIVE class).
    """
    has_stop_row = False
    has_tp_leg = False
    for algo in truth_algo_orders:
        if _get_field(algo, "symbol") != symbol:
            continue
        role = role_of_client_id(_get_field(algo, "client_algo_id"))
        if role == OrderRole.STOP_LOSS.value:
            if is_protection_confirmed(_get_field(algo, "algo_status")):
                return None
            has_stop_row = True
        elif role in (OrderRole.TAKE_PROFIT_1.value, OrderRole.TAKE_PROFIT_2.value):
            has_tp_leg = True
    if has_tp_leg and not has_stop_row:
        return DIVERGENCE_KIND_TP_ONLY_POSITION
    return DIVERGENCE_KIND_POSITION_WITHOUT_STOP


def _duplicate_id_divergence(
    first_row: Any, client_id: str, *, is_algo: bool = False
) -> Divergence:
    symbol = _get_field(first_row, "symbol")
    return Divergence(
        kind=DIVERGENCE_KIND_DUPLICATE_EXCHANGE_ID,
        symbol=symbol if isinstance(symbol, str) and symbol != "" else "UNKNOWN",
        order_role=role_of_client_id(client_id) or "UNKNOWN",
        client_order_id=None if is_algo else client_id,
        client_algo_id=client_id if is_algo else None,
        reason="the same client id appears more than once in the exchange truth",
    )


def _unowned_order_divergence(row: Any, order_id: Any, *, is_algo: bool) -> Divergence:
    """The divergence for an exchange order that no open local intent owns.

    FOREIGN_ORDER when the id is absent or does not carry this system's prefix,
    UNTRACKED_SYSTEM_ORDER when it does. Neither is ever sweepable.
    """
    symbol = _get_field(row, "symbol")
    usable_id = order_id if isinstance(order_id, str) and order_id != "" else None
    if usable_id is not None and is_system_client_id(usable_id):
        kind = DIVERGENCE_KIND_UNTRACKED_SYSTEM_ORDER
        reason = "exchange order with a system id and no local intent"
    else:
        kind = DIVERGENCE_KIND_FOREIGN_ORDER
        reason = "exchange order this system did not create (no local intent, foreign id)"
    return Divergence(
        kind=kind,
        symbol=symbol if isinstance(symbol, str) and symbol != "" else "UNKNOWN",
        order_role=(usable_id and role_of_client_id(usable_id)) or "UNKNOWN",
        client_order_id=None if is_algo else usable_id,
        client_algo_id=usable_id if is_algo else None,
        reason=reason,
    )


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
    "LocalActivePlan",
    "OrphanProtective",
    "DIVERGENCE_KIND_ORPHAN_PROTECTIVE",
    "DIVERGENCE_KIND_UNSYNCED_NORMAL",
    "DIVERGENCE_KIND_UNSYNCED_ALGO",
    "DIVERGENCE_KIND_UNSYNCED_POSITION",
    "DIVERGENCE_KIND_FOREIGN_ORDER",
    "DIVERGENCE_KIND_UNTRACKED_SYSTEM_ORDER",
    "DIVERGENCE_KIND_DUPLICATE_EXCHANGE_ID",
    "DIVERGENCE_KIND_DOUBLED_POSITION",
    "DIVERGENCE_KIND_SIGN_FLIPPED_POSITION",
    "DIVERGENCE_KIND_TP_ONLY_POSITION",
    "DIVERGENCE_KIND_POSITION_WITHOUT_STOP",
    "DIVERGENCE_KIND_AMBIGUOUS_POSITION_OWNER",
    "DIVERGENCE_KIND_UNSUPPORTED_POSITION_SIDE",
    "DIVERGENCE_KIND_STREAM_SINK_FAILURE",
    "DIVERGENCE_KIND_STREAM_TASK_DIED",
]
