"""RUNBOOK drill rehearsal tests (Phase 8, plan 08-05).

Per D-05 (OPS-01 acceptance proof): every RUNBOOK procedure must be
rehearsed with an injected fault before live enablement, with a
journaled outcome proving the rehearsal ran end-to-end. The drill
harness drives the 08-01 approval core, the 08-02 receiver seam, and
the 08-04 reconciler / sweeper / SAFE_MODE through fakes only — it
NEVER touches the network, places a real order, or creates real
unprotected exposure.

The tests cover:

  1. The 8 RUNBOOK drills (unprotected, orphan, duplicate, api_down,
     stale_feed, db_failure, manual_close, restore) each rehearse
     with an injected fault and journal a DRILL_OUTCOME event.
  2. The ordered drill log matches the golden fixture
     (`tests/fixtures/phase8/drill_log/expected.json`).
  3. Double-run determinism: running the drill suite twice with the
     same `now_utc` sequence produces a byte-identical ordered
     outcome list.
  4. The narrowed placement rule (Phase 20, plan 20-23, F-604, D034/D077): the
     reconciler (`src/reconcile`) never calls a placement method; a protective
     action it delegates is placed by the coordinator in `src/execution`, and
     that placement carries the plan's own stop price and deterministic id.
  5. SAFE_MODE exit is rehearsed only through the restore path
     (Pitfall 4: a boolean flip without both a clean compare AND a
     journaled restore event is rejected).
  6. Phase 20 (D-27, D-28, G2-016): the UNPROTECTED and STALE_FEED drills run through
     a real `ReconcileLoop` tick, and the MANUAL_CLOSE drill runs through
     `emergency_manual_close` and the sweeper, for both answers to G4-035.

Evidence label: executed tests with fakes. Nothing touches Binance, Telegram or a database;
the real-stack RUNBOOK rehearsal is Phases 25/26 [NOT_TESTED on Demo].
"""

from __future__ import annotations

import ast
import json
import sys
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.domain.enums import OrderRole, OrderStatus
from src.execution.order_ids import derive_algo_client_id, derive_client_order_id

from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
from tests.support.reconcile_doubles import (
    RecordingJournal,
    make_algo_order,
    make_plan_protection,
    make_position,
)
from tests.support.reconcile_rig import FakeFeedSource, Rig, build_rig

PHASE8_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase8"
DRILL_LOG_FIXTURE_DIR = PHASE8_FIXTURES_DIR / "drill_log"

# Registry of every fake adapter built by
# `_build_all_drill_declarations` for the latest call. The
# no-place-order runtime test reads this registry because the fakes
# are otherwise function-local and inaccessible.
BUILT_DRILL_ADAPTERS: list[Any] = []

#: The loop-driven drills (plan 20-23): the rigs and fake exchanges of the latest build.
BUILT_LOOP_RIGS: list[Rig] = []
BUILT_MANUAL_CLOSE: list[Any] = []

DRILL_NOW = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)
PLAN_H = "1" * 64
MANUAL_PLAN_HASH = "6" * 64
MANUAL_SYMBOL = "BTCUSDT"
MANUAL_QUANTITY = Decimal("0.004")
MANUAL_PRICE = Decimal("60000")
SRC_ROOT = Path(__file__).parent.parent / "src"

#: Methods that place something on the exchange (the adapter surface plus the legacy names).
PLACEMENT_METHODS: tuple[str, ...] = (
    "place_order",
    "place_algo_order",
    "place_entry",
    "place_algo_protective",
    "place_market_close",
)


@dataclass(frozen=True)
class PlacementCall:
    """One placement call: the method, the module that called it and the keywords."""

    method: str
    caller: str
    kwargs: dict[str, Any]


async def _already_done() -> None:
    return None


def record_placements(adapter: Any) -> list[PlacementCall]:
    """Wrap the placement methods of `adapter` so each call is recorded with its caller module.

    The wrapper is a plain function: `sys._getframe(1)` is the frame that made the call, so
    `f_globals["__name__"]` is the module of the caller (`src.reconcile.loop`,
    `src.execution.protection`, ...). The real method still runs (a recording wrapper never
    raises), so a coordinator placement reaches the fake exchange as usual.
    """
    calls: list[PlacementCall] = []

    def wrap(name: str) -> None:
        original = getattr(adapter, name, None)
        if original is None:
            return

        def recording(**kwargs: Any) -> Any:
            caller = sys._getframe(1).f_globals.get("__name__", "?")
            calls.append(PlacementCall(method=name, caller=caller, kwargs=dict(kwargs)))
            return original(**kwargs)

        setattr(adapter, name, recording)

    for name in PLACEMENT_METHODS:
        wrap(name)
    return calls


# --------------------------------------------------------------------------- #
# Helpers — fakes shared across the drill tests.
# --------------------------------------------------------------------------- #


class _FakeJournal:
    """Captures JournalEvents emitted by the system under test.

    Mirrors the fake-journal pattern from prior phases: records every
    event in insertion order; tests assert event_type / entity_type /
    payload keys against the fixture expected values.
    """

    def __init__(self) -> None:
        self.events: list[Any] = []

    def record(self, event: Any) -> None:
        self.events.append(event)


class _FakeReconcileAdapter:
    """Fake three-source exchange adapter for drill tests.

    Mirrors the FakeReconcileAdapter pattern from
    `tests/test_reconcile.py`: records every query + cancel call and
    returns the pre-configured truth. Tests inject this in place of
    the real `BinanceUsdmAdapter` so unit tests never touch the
    network.

    Phase 20 (F-604, D034/D077): the reconciler places nothing, but a placement by a
    DIFFERENT module (the coordinator in `src/execution`) is legitimate. The placement
    methods therefore RECORD the call with the caller's module name and never raise; the
    tests assert which module called (none from `src/reconcile`, `src/ops`). The static
    guard at the end of the file keeps the source-level rule for `src/ops`.
    """

    def __init__(
        self,
        *,
        normal_orders: list[Any] | None = None,
        algo_orders: list[Any] | None = None,
        positions: list[Any] | None = None,
        position_reads: list[Decimal] | None = None,
        raise_on_query: type[Exception] | None = None,
    ) -> None:
        self._normal_orders = list(normal_orders or [])
        self._algo_orders = list(algo_orders or [])
        self._positions = list(positions or [])
        self._position_reads = list(position_reads or [])
        self._position_read_index = 0
        self._raise_on_query = raise_on_query

        self.snapshot_open_normal_orders_calls = 0
        self.snapshot_open_algo_orders_calls = 0
        self.snapshot_positions_calls = 0
        self.query_algo_order_by_client_calls: list[str] = []
        self.cancel_normal_order_calls: list[tuple[str, str]] = []
        self.cancel_algo_order_calls: list[tuple[str, str]] = []
        self.place_order_calls = 0
        self.placement_callers: list[str] = []

    async def snapshot_open_normal_orders(self, *, symbol: str | None = None) -> list[Any]:
        self.snapshot_open_normal_orders_calls += 1
        if symbol is None:
            return list(self._normal_orders)
        return [o for o in self._normal_orders if o.symbol == symbol]

    async def snapshot_open_algo_orders(self, *, symbol: str | None = None) -> list[Any]:
        self.snapshot_open_algo_orders_calls += 1
        if symbol is None:
            return list(self._algo_orders)
        return [o for o in self._algo_orders if o.symbol == symbol]

    async def snapshot_positions(self, *, symbol: str | None = None) -> list[Any]:
        self.snapshot_positions_calls += 1
        if symbol is None:
            return list(self._positions)
        return [o for o in self._positions if o.symbol == symbol]

    def read_position(self, *, symbol: str) -> Decimal:
        """Read one position amount from the configured sequence."""
        if self._position_read_index >= len(self._position_reads):
            value = self._position_reads[-1] if self._position_reads else Decimal("0")
        else:
            value = self._position_reads[self._position_read_index]
            self._position_read_index += 1
        return value

    async def query_algo_order_by_client(self, *, client_algo_id: str) -> Any:
        from src.adapters.binance_usdm import AlgoOrderProbe

        self.query_algo_order_by_client_calls.append(client_algo_id)
        if self._raise_on_query is not None:
            raise self._raise_on_query("simulated API degradation")
        for order in self._algo_orders:
            if order.client_algo_id == client_algo_id:
                return AlgoOrderProbe(
                    client_algo_id=client_algo_id,
                    found=True,
                    algo_status=order.algo_status,
                    update_time_utc=order.update_time_utc,
                )
        return AlgoOrderProbe(
            client_algo_id=client_algo_id,
            found=False,
            algo_status=None,
            update_time_utc=None,
        )

    async def cancel_normal_order(self, *, symbol: str, orig_client_order_id: str) -> None:
        self.cancel_normal_order_calls.append((symbol, orig_client_order_id))
        self._normal_orders = [
            o
            for o in self._normal_orders
            if not (o.symbol == symbol and o.client_order_id == orig_client_order_id)
        ]

    async def cancel_algo_order(self, *, symbol: str, client_algo_id: str) -> None:
        self.cancel_algo_order_calls.append((symbol, client_algo_id))
        self._algo_orders = [
            o
            for o in self._algo_orders
            if not (o.symbol == symbol and o.client_algo_id == client_algo_id)
        ]

    def place_order(self, **_kwargs: Any) -> Awaitable[None]:
        """Record a placement attempt with the caller module (F-604); never raises."""
        return self._record_placement(sys._getframe(1).f_globals.get("__name__", "?"))

    def place_algo_order(self, **_kwargs: Any) -> Awaitable[None]:
        """Record a placement attempt with the caller module (F-604); never raises."""
        return self._record_placement(sys._getframe(1).f_globals.get("__name__", "?"))

    def _record_placement(self, caller: str) -> Awaitable[None]:
        self.place_order_calls += 1
        self.placement_callers.append(caller)
        return _already_done()


def _build_open_order(row: dict[str, Any]) -> Any:
    from src.adapters.binance_usdm import OpenOrderSnapshot

    return OpenOrderSnapshot(
        symbol=row["symbol"],
        client_order_id=row["client_order_id"],
        exchange_order_id=row["exchange_order_id"],
        side=row["side"],
        position_side=row["position_side"],
        order_type=row["order_type"],
        time_in_force=row["time_in_force"],
        status=row["status"],
        quantity=Decimal(str(row["quantity"])),
        price=Decimal(str(row["price"])) if row.get("price") else None,
        stop_price=(Decimal(str(row["stop_price"])) if row.get("stop_price") else None),
        reduce_only=row.get("reduce_only", False),
        close_position=row.get("close_position", False),
        working_type=row.get("working_type"),
        price_protect=row.get("price_protect"),
        update_time_utc=_parse_utc(row["update_time_utc"]),
    )


def _build_open_algo_order(row: dict[str, Any]) -> Any:
    from src.adapters.binance_usdm import OpenAlgoOrderSnapshot

    return OpenAlgoOrderSnapshot(
        symbol=row["symbol"],
        client_algo_id=row["client_algo_id"],
        algo_id=row["algo_id"],
        algo_type=row["algo_type"],
        order_type=row["order_type"],
        side=row["side"],
        position_side=row["position_side"],
        time_in_force=row["time_in_force"],
        algo_status=row["algo_status"],
        quantity=Decimal(str(row["quantity"])),
        trigger_price=(Decimal(str(row["trigger_price"])) if row.get("trigger_price") else None),
        price=Decimal(str(row["price"])) if row.get("price") else None,
        trigger_time_utc=(
            _parse_utc(row["trigger_time_utc"]) if row.get("trigger_time_utc") else None
        ),
        working_type=row.get("working_type"),
        close_position=row.get("close_position", False),
        reduce_only=row.get("reduce_only", False),
        update_time_utc=_parse_utc(row["update_time_utc"]),
    )


def _build_position(row: dict[str, Any]) -> Any:
    from src.adapters.binance_usdm import PositionSnapshot

    return PositionSnapshot(
        symbol=row["symbol"],
        position_side=row["position_side"],
        position_amt=Decimal(str(row["position_amt"])),
        entry_price=Decimal(str(row["entry_price"])),
        break_even_price=Decimal(str(row["break_even_price"])),
        mark_price=(Decimal(str(row["mark_price"])) if row.get("mark_price") else None),
        unrealized_profit=Decimal(str(row["unrealized_profit"])),
        liquidation_price=(
            Decimal(str(row["liquidation_price"])) if row.get("liquidation_price") else None
        ),
        notional=Decimal(str(row["notional"])) if row.get("notional") else None,
        margin_asset=row["margin_asset"],
        update_time_utc=_parse_utc(row["update_time_utc"]),
    )


def _parse_utc(raw: str) -> datetime:
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None:
        raise ValueError(f"naive datetime in fixture: {raw!r}")
    return value.astimezone(UTC)


def _make_local_intent(fixture: dict[str, Any]) -> dict[str, Any]:
    """Translate the fixture's local_intent block to the types
    compare() consumes (lightweight frozen-like tuples / dicts)."""
    from src.domain.enums import OrderRole, OrderStatus

    open_orders: list[dict[str, Any]] = []
    for o in fixture["local_intent"]["open_orders"]:
        open_orders.append(
            {
                "client_order_id": o["client_order_id"],
                "symbol": o["symbol"],
                "order_role": OrderRole(o["order_role"]),
                "status": OrderStatus(o["status"]),
            }
        )
    open_algos: list[dict[str, Any]] = []
    for a in fixture["local_intent"]["open_algos"]:
        open_algos.append(
            {
                "client_algo_id": a["client_algo_id"],
                "symbol": a["symbol"],
                "order_role": OrderRole(a["order_role"]),
                "status": OrderStatus(a["status"]),
            }
        )
    open_positions: list[dict[str, Any]] = []
    for p in fixture["local_intent"]["open_positions"]:
        open_positions.append(
            {
                "symbol": p["symbol"],
                "position_side": p["position_side"],
                "position_amt": Decimal(str(p["position_amt"])),
            }
        )
    return {
        "open_orders": open_orders,
        "open_algos": open_algos,
        "open_positions": open_positions,
    }


def _make_truth(fixture: dict[str, Any]) -> dict[str, Any]:
    return {
        "normal_orders": [_build_open_order(o) for o in fixture["exchange_truth"]["normal_orders"]],
        "algo_orders": [
            _build_open_algo_order(o) for o in fixture["exchange_truth"]["algo_orders"]
        ],
        "positions": [_build_position(p) for p in fixture["exchange_truth"]["positions"]],
    }


# --------------------------------------------------------------------------- #
# Drill scenario builders — one per RUNBOOK procedure.
# --------------------------------------------------------------------------- #


def _build_orphan_scenario() -> dict[str, Any]:
    """Build the ORPHAN drill scenario (§4).

    Local intent has a STOP_LOSS algo for BTCUSDT but no local
    position and no exchange position, and the plan's ENTRY is no longer
    open (Phase 20, D-05: a protective of a resting entry is not an
    orphan). The compare classifies ORPHAN_PROTECTIVE divergence; the
    sweeper cancels the algo after authoritative position-zero
    verification.
    """
    return {
        "local_intent": {
            "open_orders": [],
            "open_algos": [
                {
                    "client_algo_id": "xa-1111111111111111111111111111111SL",
                    "symbol": "BTCUSDT",
                    "order_role": "STOP_LOSS",
                    "status": "NEW",
                }
            ],
            "open_positions": [],
        },
        "exchange_truth": {
            "normal_orders": [],
            "algo_orders": [
                {
                    "symbol": "BTCUSDT",
                    "client_algo_id": "xa-1111111111111111111111111111111SL",
                    "algo_id": "200001",
                    "algo_type": "CONDITIONAL",
                    "order_type": "STOP_MARKET",
                    "side": "SELL",
                    "position_side": "LONG",
                    "time_in_force": "GTC",
                    "algo_status": "NEW",
                    "quantity": "0.010",
                    "trigger_price": "49000.00",
                    "price": None,
                    "trigger_time_utc": None,
                    "working_type": "CONTRACT_PRICE",
                    "close_position": False,
                    "reduce_only": True,
                    "update_time_utc": "2026-09-19T10:00:00+00:00",
                }
            ],
            "positions": [],
        },
    }


MANUAL_LEG_ROLES: tuple[str, ...] = ("STOP_LOSS", "TAKE_PROFIT_1", "TAKE_PROFIT_2")


def _manual_leg_ids() -> dict[str, str]:
    return {
        role: derive_algo_client_id(plan_hash=MANUAL_PLAN_HASH, role=role)
        for role in MANUAL_LEG_ROLES
    }


async def _prepare_manual_exchange(
    *, position_open: bool, legs_auto_cancelled: bool
) -> BinanceSemanticsFakeAdapter:
    """The Binance-semantics fake holding a filled entry and the three protective legs.

    `position_open=False` models the operator closing the position on the exchange itself
    (outside the system). `legs_auto_cancelled=True` is the first answer to G4-035 (the
    exchange removes the closePosition legs with the position), False the second (they stay).
    Both answers are modelled by the fake only; what Binance does is [NOT_TESTED] (Phase 25).
    """
    fake = BinanceSemanticsFakeAdapter()
    entry_id = derive_client_order_id(plan_hash=MANUAL_PLAN_HASH, role="ENTRY")
    await fake.place_entry(
        symbol=MANUAL_SYMBOL,
        side="BUY",
        position_side="BOTH",
        time_in_force="GTC",
        quantity=MANUAL_QUANTITY,
        price=MANUAL_PRICE,
        new_client_order_id=entry_id,
    )
    fake.fill(entry_id)
    for role, client_algo_id in _manual_leg_ids().items():
        stop = role == "STOP_LOSS"
        await fake.place_algo_protective(
            symbol=MANUAL_SYMBOL,
            side="SELL",
            algo_type="CONDITIONAL",
            type="STOP_MARKET" if stop else "TAKE_PROFIT_MARKET",
            position_side="BOTH",
            trigger_price=Decimal("59000") if stop else Decimal("61000"),
            close_position=stop,
            quantity=None if stop else MANUAL_QUANTITY / 2,
            working_type="MARK_PRICE",
            client_algo_id=client_algo_id,
            reduce_only=None if stop else True,
        )
    if not position_open:
        fake.positions[MANUAL_SYMBOL] = Decimal("0")
    if legs_auto_cancelled:
        for client_algo_id in _manual_leg_ids().values():
            fake.cancel_algo(client_algo_id)
    fake.calls.clear()
    return fake


def _manual_local_intent(*, position_open: bool) -> dict[str, Any]:
    """The local view the drill compares against: the three legs, the position if still open."""
    return {
        "open_orders": [],
        "open_algos": [
            {
                "client_algo_id": client_algo_id,
                "symbol": MANUAL_SYMBOL,
                "order_role": OrderRole(role),
                "status": OrderStatus.NEW,
            }
            for role, client_algo_id in _manual_leg_ids().items()
        ],
        "open_positions": (
            [{"symbol": MANUAL_SYMBOL, "position_side": "BOTH", "position_amt": MANUAL_QUANTITY}]
            if position_open
            else []
        ),
    }


class _RecordingEnablement:
    def __init__(self) -> None:
        self.disabled = False

    def disable(self, *, operator_id: str, now_utc: datetime) -> None:
        self.disabled = True


@dataclass
class ManualCloseWiring:
    """What one MANUAL_CLOSE drill touched (the fake exchange, controller and journal)."""

    declaration: Any
    exchange: BinanceSemanticsFakeAdapter
    controller: Any
    journal: RecordingJournal
    enablement: _RecordingEnablement
    placements: list[PlacementCall]


def _build_manual_close_wiring(
    *, now_utc: datetime, position_open: bool = False, legs_auto_cancelled: bool = False
) -> ManualCloseWiring:
    """Build the MANUAL_CLOSE drill over the fake exchange (D-27, D-28, G2-016)."""
    import asyncio

    from src.execution.manager import emergency_manual_close
    from src.ops.drills import make_manual_close_drill
    from src.reconcile.safe_mode import SafeModeController
    from src.reconcile.sweeper import OrphanSweeper

    exchange = asyncio.run(
        _prepare_manual_exchange(
            position_open=position_open, legs_auto_cancelled=legs_auto_cancelled
        )
    )
    placements = record_placements(exchange)
    journal = RecordingJournal()
    enablement = _RecordingEnablement()
    controller = SafeModeController(
        adapter=_FakeReconcileAdapter(),  # type: ignore[arg-type]
        journal=_FakeJournal(),  # type: ignore[arg-type]
    )

    def close_control() -> Awaitable[None]:
        return emergency_manual_close(
            plan_hash=MANUAL_PLAN_HASH,
            symbol=MANUAL_SYMBOL,
            adapter=exchange,  # type: ignore[arg-type]
            journal=journal,
            enablement=enablement,
            safe_mode_controller=controller,
            operator_id="operator_alpha",
            now_utc=now_utc,
        )

    async def read_truth() -> dict[str, Any]:
        return {
            "normal_orders": await exchange.snapshot_open_normal_orders(),
            "algo_orders": await exchange.snapshot_open_algo_orders(),
            "positions": await exchange.snapshot_positions(),
        }

    def position_verifier(*, symbol: str) -> Decimal:
        return exchange.positions.get(symbol, Decimal("0"))

    declaration = make_manual_close_drill(
        close_control=close_control,
        read_truth=read_truth,
        sweeper=OrphanSweeper(adapter=exchange, journal=journal, now_utc=now_utc),  # type: ignore[arg-type]
        safe_mode_controller=controller,
        local_intent=_manual_local_intent(position_open=position_open),
        position_verifier=position_verifier,
    )
    return ManualCloseWiring(
        declaration=declaration,
        exchange=exchange,
        controller=controller,
        journal=journal,
        enablement=enablement,
        placements=placements,
    )


def _build_unprotected_rig() -> Rig:
    """A tracked PROTECTED plan, an exchange position and no stop: POSITION_WITHOUT_STOP."""
    plan = make_plan_protection(PLAN_H, symbol="BTCUSDT", state="PROTECTED")
    return build_rig(plans=(plan,), positions=(make_position("BTCUSDT", "0.004"),))


def _build_stale_feed_rig(*, stale: bool = True) -> Rig:
    """A fully agreeing PROTECTED plan whose mark price feed is (or is not) stale."""
    from src.reconcile.feed_freshness import FeedReading

    plan = make_plan_protection(PLAN_H, symbol="BTCUSDT", state="PROTECTED")
    stop = make_algo_order(
        derive_algo_client_id(plan_hash=PLAN_H, role=OrderRole.STOP_LOSS.value), "BTCUSDT"
    )
    mark_at = DRILL_NOW - (timedelta(minutes=10) if stale else timedelta(milliseconds=10))
    feed = FakeFeedSource(
        FeedReading(
            mark_price_at_utc={"BTCUSDT": mark_at},
            user_data_last_event_at_utc=DRILL_NOW - timedelta(milliseconds=10),
        )
    )
    return build_rig(
        plans=(plan,), algo=(stop,), positions=(make_position("BTCUSDT", "0.004"),), feed=feed
    )


def _build_duplicate_scenario() -> dict[str, Any]:
    """Build the DUPLICATE drill scenario (§5).

    A PENDING approval + valid binding context. The drill replays
    the same APPROVE callback 5 times and asserts exactly one
    transition.
    """
    import hashlib

    raw_token = "raw_token_drill_duplicate_001_aaaaaaaaaaaaaaaaaaaaaa"
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    return {
        "approval_id": "apprv_drill_duplicate_001",
        "trade_plan_id": "tp_drill_duplicate_001",
        "signal_id": "sig_drill_duplicate_001",
        "chat_id": 123456789,
        "action": "APPROVE",
        "raw_token": raw_token,
        "token_hash": token_hash,
        "plan_hash": "1111111111111111111111111111111111111111111111111111111111111111",
        "strategy_version": "v2.0.0",
        "parameter_set_id": "baseline-v3",
        "parameter_set_hash": "2222222222222222222222222222222222222222222222222222222222222222",
        "requested_at_utc": "2026-09-19T10:00:00+00:00",
        "expiry_utc": "2026-09-19T11:00:00+00:00",
        "callback_at_utc": "2026-09-19T10:30:00+00:00",
        "replay_count": 5,
    }


# --------------------------------------------------------------------------- #
# Drill declaration builders — compose the 8 RUNBOOK drills.
# --------------------------------------------------------------------------- #


def _build_all_drill_declarations(
    *,
    now_utc: datetime,
) -> tuple[Any, ...]:
    """Build the 8 RUNBOOK drill declarations.

    Returns a tuple of `DrillDeclaration` instances in the canonical
    `DRILL_NAMES` order. Each declaration is wired with the fakes
    needed to rehearse its scenario.
    """
    from src.ops.drills import (
        DRILL_NAMES,
        make_api_down_drill,
        make_db_failure_drill,
        make_duplicate_drill,
        make_orphan_drill,
        make_restore_drill,
        make_stale_feed_drill,
        make_unprotected_drill,
    )
    from src.reconcile.compare import compare as _compare
    from src.reconcile.safe_mode import SafeModeController
    from src.reconcile.sweeper import OrphanSweeper

    # --- UNPROTECTED (§3): a real ReconcileLoop tick (plan 20-23, D-27) -------
    unprotected_rig = _build_unprotected_rig()
    record_placements(unprotected_rig.adapter)
    unprotected_drill = make_unprotected_drill(
        loop=unprotected_rig.loop,
        safe_mode_controller=unprotected_rig.safe_mode,
        now_utc=now_utc,
    )

    # --- ORPHAN (§4) ------------------------------------------------------
    orphan = _build_orphan_scenario()
    orphan_local = _make_local_intent(orphan)
    orphan_truth = _make_truth(orphan)
    orphan_adapter = _FakeReconcileAdapter(
        normal_orders=orphan_truth["normal_orders"],
        algo_orders=orphan_truth["algo_orders"],
        positions=orphan_truth["positions"],
        position_reads=[Decimal("0"), Decimal("0")],
    )
    orphan_journal = _FakeJournal()
    orphan_controller = SafeModeController(
        adapter=orphan_adapter,  # type: ignore[arg-type]
        journal=orphan_journal,  # type: ignore[arg-type]
    )
    orphan_sweeper = OrphanSweeper(
        adapter=orphan_adapter,  # type: ignore[arg-type]
        journal=orphan_journal,  # type: ignore[arg-type]
        now_utc=now_utc,
    )
    orphan_drill = make_orphan_drill(
        compare_fn=_compare,
        sweeper=orphan_sweeper,
        safe_mode_controller=orphan_controller,
        local_intent=orphan_local,
        truth=orphan_truth,
        position_verifier=orphan_adapter.read_position,
    )

    # --- DUPLICATE (§5) ---------------------------------------------------
    duplicate = _build_duplicate_scenario()
    from src.approval.binding import Callback
    from src.approval.replay import resolve_callback

    duplicate_callback = Callback(
        raw_token=duplicate["raw_token"],
        chat_id=duplicate["chat_id"],
        plan_hash=duplicate["plan_hash"],
        strategy_version=duplicate["strategy_version"],
        parameter_set_id=duplicate["parameter_set_id"],
        parameter_set_hash=duplicate["parameter_set_hash"],
        callback_at_utc=_parse_utc(duplicate["callback_at_utc"]),
    )
    from src.domain.approval import Approval
    from src.domain.enums import ApprovalAction, ApprovalResult

    duplicate_approval = Approval(
        approval_id=duplicate["approval_id"],
        trade_plan_id=duplicate["trade_plan_id"],
        signal_id=duplicate["signal_id"],
        action=ApprovalAction(duplicate["action"]),
        result=ApprovalResult.PENDING,
        status=ApprovalResult.PENDING,
        approval_token_hash=duplicate["token_hash"],
        requested_at_utc=_parse_utc(duplicate["requested_at_utc"]),
        acted_at_utc=None,
        actor_id="",
        telegram_message_id=None,
        request_hash=duplicate["plan_hash"],
    )

    # In-memory store keyed by token hash (the idempotency key).
    # The save() callable updates the store so subsequent lookups
    # return the transitioned approval (replay-to-existing semantics).
    _duplicate_store: dict[str, Any] = {duplicate_approval.approval_token_hash: duplicate_approval}

    def _duplicate_lookup(token_hash: str) -> Any:
        return _duplicate_store.get(token_hash)

    def _duplicate_save(approval: Any) -> None:
        _duplicate_store[approval.approval_token_hash] = approval

    duplicate_binding_context = {
        "authorized_chat_id": duplicate["chat_id"],
        "expiry_utc": _parse_utc(duplicate["expiry_utc"]),
        "approval_strategy_version": duplicate["strategy_version"],
        "approval_parameter_set_id": duplicate["parameter_set_id"],
        "approval_parameter_set_hash": duplicate["parameter_set_hash"],
    }
    duplicate_drill = make_duplicate_drill(
        resolve_callback_fn=resolve_callback,
        callback=duplicate_callback,
        lookup_by_token_hash=_duplicate_lookup,
        save=_duplicate_save,
        binding_context=duplicate_binding_context,
        replay_count=duplicate["replay_count"],
    )

    # --- API_DOWN (§10) ---------------------------------------------------
    api_down_adapter = _FakeReconcileAdapter(
        raise_on_query=RuntimeError,
    )
    api_down_journal = _FakeJournal()
    api_down_controller = SafeModeController(
        adapter=api_down_adapter,  # type: ignore[arg-type]
        journal=api_down_journal,  # type: ignore[arg-type]
    )

    def _api_down_call() -> None:
        raise RuntimeError("simulated API degradation")

    api_down_drill = make_api_down_drill(
        safe_mode_controller=api_down_controller,
        api_call=_api_down_call,
    )

    # --- STALE_FEED (§7): the loop's own feed check (plan 20-23, D-25, D-27) ---
    stale_feed_rig = _build_stale_feed_rig()
    record_placements(stale_feed_rig.adapter)
    stale_feed_drill = make_stale_feed_drill(
        loop=stale_feed_rig.loop,
        safe_mode_controller=stale_feed_rig.safe_mode,
        now_utc=now_utc,
    )

    # --- DB_FAILURE (§9) --------------------------------------------------
    db_failure_adapter = _FakeReconcileAdapter()
    db_failure_journal = _FakeJournal()
    db_failure_controller = SafeModeController(
        adapter=db_failure_adapter,  # type: ignore[arg-type]
        journal=db_failure_journal,  # type: ignore[arg-type]
    )

    def _db_failure_write() -> None:
        raise RuntimeError("simulated DB failure")

    db_failure_drill = make_db_failure_drill(
        safe_mode_controller=db_failure_controller,
        db_write=_db_failure_write,
    )

    # --- MANUAL_CLOSE (§12): emergency_manual_close + sweeper (plan 20-23, D-28) ---
    manual_close_wiring = _build_manual_close_wiring(now_utc=now_utc)
    manual_close_drill = manual_close_wiring.declaration

    # --- RESTORE (clean exit) ---------------------------------------------
    # The restore drill needs a controller that can exit cleanly. The
    # fake adapter returns empty truth, so the controller's compare
    # yields agreement=True and the exit path succeeds.
    restore_adapter = _FakeReconcileAdapter()
    restore_journal = _FakeJournal()
    restore_controller = SafeModeController(
        adapter=restore_adapter,  # type: ignore[arg-type]
        journal=restore_journal,  # type: ignore[arg-type]
    )
    restore_drill = make_restore_drill(
        safe_mode_controller=restore_controller,
        enter_reason="INITIAL_SAFE_MODE",
        now_utc=now_utc,
    )

    # Return in canonical DRILL_NAMES order.
    by_name = {
        "unprotected": unprotected_drill,
        "orphan": orphan_drill,
        "duplicate": duplicate_drill,
        "api_down": api_down_drill,
        "stale_feed": stale_feed_drill,
        "db_failure": db_failure_drill,
        "manual_close": manual_close_drill,
        "restore": restore_drill,
    }
    BUILT_DRILL_ADAPTERS.clear()
    BUILT_DRILL_ADAPTERS.extend(
        [
            orphan_adapter,
            api_down_adapter,
            db_failure_adapter,
            restore_adapter,
        ]
    )
    BUILT_LOOP_RIGS.clear()
    BUILT_LOOP_RIGS.extend([unprotected_rig, stale_feed_rig])
    BUILT_MANUAL_CLOSE.clear()
    BUILT_MANUAL_CLOSE.append(manual_close_wiring)
    return tuple(by_name[name] for name in DRILL_NAMES)


def _build_now_utc_sequence(base: datetime) -> tuple[datetime, ...]:
    """Build the 8-timestamp sequence for the drill run.

    Each timestamp is `base + N seconds` so the sequence is
    deterministic and the journal_event_id values are stable across
    repeat runs.
    """
    return tuple(
        datetime(
            base.year,
            base.month,
            base.day,
            base.hour,
            base.minute,
            base.second + index,
            tzinfo=UTC,
        )
        for index in range(8)
    )


# --------------------------------------------------------------------------- #
# Test 1 — the 8 RUNBOOK drills each rehearse with an injected fault.
# --------------------------------------------------------------------------- #


def test_eight_drills_rehearse_with_injected_faults() -> None:
    """Beh. 1: all eight RUNBOOK drills rehearse with injected faults
    and journal a DRILL_OUTCOME event.

    Per D-05: the drill harness drives the 08-01 approval core, the
    08-02 receiver seam, and the 08-04 reconciler / sweeper /
    SAFE_MODE through fakes only. Each drill injects an in-memory
    fake fault, asserts the expected SAFE_MODE / sweep / journal
    outcome, and emits a JournalEvent with event_type DRILL_OUTCOME.
    """
    from src.ops.drills import (
        ALL_OUTCOMES,
        DRILL_NAMES,
        OUTCOME_ORPHAN_SWEPTED,
        OUTCOME_REPLAY_TRANSITIONED,
        OUTCOME_RESTORE_CLEAN_EXIT,
        OUTCOME_SAFE_MODE_BLOCKED,
        OUTCOME_SAFE_MODE_ENTERED,
        DrillLog,
        run_all_drills,
    )

    base = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)
    now_utc_sequence = _build_now_utc_sequence(base)
    declarations = _build_all_drill_declarations(now_utc=base)
    journal = DrillLog()

    outcomes = run_all_drills(
        declarations,
        journal=journal,
        now_utc_sequence=now_utc_sequence,
    )

    # Eight outcomes, one per drill, in canonical order.
    assert len(outcomes) == 8
    assert tuple(o.drill for o in outcomes) == DRILL_NAMES

    # Every outcome is a canonical OUTCOME_* string.
    for outcome in outcomes:
        assert outcome.outcome in ALL_OUTCOMES

    # The journal has exactly 8 DRILL_OUTCOME events in canonical order.
    drill_events = journal.drill_outcome_events()
    assert len(drill_events) == 8
    assert journal.ordered_drill_outcomes() == DRILL_NAMES

    # Each DRILL_OUTCOME event carries the drill name, fault, outcome,
    # and UTC timestamp in its payload.
    for event, outcome in zip(drill_events, outcomes, strict=True):
        assert event.event_type == "DRILL_OUTCOME"
        assert event.entity_type == "Drill"
        assert event.entity_id == outcome.drill
        payload = json.loads(event.payload_json)
        assert payload["drill"] == outcome.drill
        assert payload["fault"] == outcome.fault
        assert payload["outcome"] == outcome.outcome
        assert payload["occurred_at_utc"] == outcome.occurred_at_utc.isoformat()
        assert payload["runbook_section"] != ""

    # The expected outcome per drill (matches the RUNBOOK procedure).
    expected_outcomes = {
        "unprotected": OUTCOME_SAFE_MODE_BLOCKED,
        "orphan": OUTCOME_ORPHAN_SWEPTED,
        "duplicate": OUTCOME_REPLAY_TRANSITIONED,
        "api_down": OUTCOME_SAFE_MODE_ENTERED,
        "stale_feed": OUTCOME_SAFE_MODE_BLOCKED,
        "db_failure": OUTCOME_SAFE_MODE_ENTERED,
        "manual_close": OUTCOME_ORPHAN_SWEPTED,
        "restore": OUTCOME_RESTORE_CLEAN_EXIT,
    }
    for outcome in outcomes:
        assert outcome.outcome == expected_outcomes[outcome.drill], (
            f"drill {outcome.drill!r}: expected "
            f"{expected_outcomes[outcome.drill]!r}, got {outcome.outcome!r}"
        )


# --------------------------------------------------------------------------- #
# Test 2 — the ordered drill log matches the golden fixture.
# --------------------------------------------------------------------------- #


def test_drill_log_matches_golden_fixture() -> None:
    """Beh. 2: the ordered drill log matches the golden fixture
    (`tests/fixtures/phase8/drill_log/expected.json`).

    The golden fixture pins the ordered eight-outcome log: drill
    names, fault strings, outcome strings, and UTC timestamps. A
    missing drill or a reordered entry fails the suite.
    """
    from src.ops.drills import DrillLog, run_all_drills

    base = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)
    now_utc_sequence = _build_now_utc_sequence(base)
    declarations = _build_all_drill_declarations(now_utc=base)
    journal = DrillLog()

    run_all_drills(
        declarations,
        journal=journal,
        now_utc_sequence=now_utc_sequence,
    )

    expected_path = DRILL_LOG_FIXTURE_DIR / "expected.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))

    # The golden fixture pins the ordered drill names.
    assert expected["drill_names"] == list(journal.ordered_drill_outcomes())

    # The golden fixture pins the ordered outcomes.
    actual_outcomes = [
        json.loads(e.payload_json)["outcome"] for e in journal.drill_outcome_events()
    ]
    assert expected["outcomes"] == actual_outcomes

    # The golden fixture pins the ordered faults.
    actual_faults = [json.loads(e.payload_json)["fault"] for e in journal.drill_outcome_events()]
    assert expected["faults"] == actual_faults

    # The golden fixture pins the ordered UTC timestamps.
    actual_timestamps = [
        json.loads(e.payload_json)["occurred_at_utc"] for e in journal.drill_outcome_events()
    ]
    assert expected["occurred_at_utc"] == actual_timestamps


# --------------------------------------------------------------------------- #
# Test 3 — double-run determinism: byte-identical ordered outcome names.
# --------------------------------------------------------------------------- #


def test_double_run_drill_log_is_byte_identical() -> None:
    """Beh. 3: running the drill suite twice with the same `now_utc`
    sequence produces a byte-identical ordered outcome list.

    Per D-05: parallel or interrupted drill runs must never corrupt
    the drill log ordering or duplicate outcome rows. The harness
    uses caller-supplied timestamps (never wall-clock) so repeat
    runs are deterministic. Each run uses FRESH fakes (fresh store,
    fresh adapters, fresh controllers) so the drill outcomes are
    independent across runs.
    """
    from src.ops.drills import DrillLog, run_all_drills

    base = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)
    now_utc_sequence = _build_now_utc_sequence(base)

    # First run with fresh fakes.
    declarations_1 = _build_all_drill_declarations(now_utc=base)
    journal_1 = DrillLog()
    run_all_drills(
        declarations_1,
        journal=journal_1,
        now_utc_sequence=now_utc_sequence,
    )

    # Second run with FRESH fakes (new store, adapters, controllers).
    declarations_2 = _build_all_drill_declarations(now_utc=base)
    journal_2 = DrillLog()
    run_all_drills(
        declarations_2,
        journal=journal_2,
        now_utc_sequence=now_utc_sequence,
    )

    # The ordered outcome names are byte-identical.
    assert journal_1.ordered_drill_outcomes() == journal_2.ordered_drill_outcomes()

    # The full event payloads are byte-identical (same timestamps,
    # same faults, same outcomes).
    payloads_1 = [e.payload_json for e in journal_1.drill_outcome_events()]
    payloads_2 = [e.payload_json for e in journal_2.drill_outcome_events()]
    assert payloads_1 == payloads_2


# --------------------------------------------------------------------------- #
# Test 4 — the narrowed placement rule (Phase 20, plan 20-23, F-604, D034/D077).
# --------------------------------------------------------------------------- #


def test_reconcile_never_places_and_delegated_stops_keep_the_plan_price() -> None:
    """Beh. 4 (F-604, D034/D077, D-27, criterion 5): the reconciler places nothing, the
    coordinator places the delegated stop with the plan's own price.

    Rewritten from `test_no_place_order_invariant_across_all_drills`, which asserted "no
    drill places anything at all" (the pre-D034 rule, 08-REVIEW IN-08). The narrowed rule has
    two halves, both asserted here:

    1. Over the full drill run, no placement call came from `src/reconcile` or `src/ops`
       (every adapter records the caller's module), and the legacy fakes saw none.
    2. A stop-related divergence is handed to the REAL coordinator by a loop tick; the
       placement that follows comes from `src.execution.protection`, is a STOP_MARKET with
       the plan's `sl_trigger_price` and the deterministic STOP_LOSS client id.
    """
    import asyncio

    from src.ops.drills import (
        OUTCOME_SAFE_MODE_BLOCKED,
        DrillLog,
        make_unprotected_drill,
        run_all_drills,
        run_drill,
    )
    from src.reconcile.loop import ReconcileLoop
    from src.reconcile.safe_mode import SafeModeController
    from src.reconcile.sweeper import OrphanSweeper

    from tests.support.execution_limits import test_only_execution_limits as make_test_limits
    from tests.support.protection_doubles import make_rig
    from tests.support.reconcile_doubles import (
        FakeGate,
        FakeIntentStore,
        InMemorySafeModeStore,
        RecordingAlertSink,
    )

    # --- half 1: the full drill run places nothing from the reconciler or the drills ------
    base = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)
    declarations = _build_all_drill_declarations(now_utc=base)
    run_all_drills(
        declarations,
        journal=DrillLog(),
        now_utc_sequence=_build_now_utc_sequence(base),
    )
    assert len(BUILT_DRILL_ADAPTERS) > 0, "expected the drill builder to register fake adapters"
    for adapter in BUILT_DRILL_ADAPTERS:
        assert adapter.place_order_calls == 0, (
            f"a placement reached a drill adapter: {adapter.placement_callers}"
        )
    assert len(BUILT_LOOP_RIGS) == 2
    for rig in BUILT_LOOP_RIGS:
        assert rig.adapter.forbidden_calls == []
    (manual_close,) = BUILT_MANUAL_CLOSE
    assert manual_close.placements == []

    # --- half 2: a delegated stop goes through the coordinator --------------------------------
    rig = asyncio.run(make_rig())
    rig.fake.fill(rig.entry_id, quantity=rig.entry.entry_quantity)  # exchange-side fill, unseen
    placements = record_placements(rig.fake)
    safe_mode = SafeModeController(
        adapter=rig.fake,  # type: ignore[arg-type]
        journal=RecordingJournal(),
        state_store=InMemorySafeModeStore(),
    )
    loop = ReconcileLoop(
        adapter=rig.fake,  # type: ignore[arg-type]
        gate=FakeGate(),
        safe_mode=safe_mode,
        intent_store=FakeIntentStore(),
        protection=rig.coordinator,
        sweeper=OrphanSweeper(adapter=rig.fake, journal=RecordingJournal()),  # type: ignore[arg-type]
        alerts=RecordingAlertSink(),
        journal=RecordingJournal(),
        limits=make_test_limits(),
    )
    outcome = run_drill(
        make_unprotected_drill(loop=loop, safe_mode_controller=safe_mode, now_utc=base),
        journal=DrillLog(),
        now_utc=base,
    )
    assert outcome.outcome == OUTCOME_SAFE_MODE_BLOCKED
    assert placements == [], "the reconcile tick placed something"

    asyncio.run(rig.coordinator.step())  # the coordinator re-checks and decides (D077)

    (stop,) = [c for c in placements if c.method == "place_algo_protective"]
    assert [c.method for c in placements] == ["place_algo_protective"]
    assert stop.caller == "src.execution.protection"
    assert not [c for c in placements if c.caller.startswith(("src.reconcile", "src.ops"))]
    assert stop.kwargs["type"] == "STOP_MARKET"
    assert stop.kwargs["trigger_price"] == rig.entry.sl_trigger_price
    assert stop.kwargs["client_algo_id"] == derive_algo_client_id(
        plan_hash=rig.entry.plan_hash, role=OrderRole.STOP_LOSS.value
    )
    assert stop.kwargs["client_algo_id"] == rig.stop_id


def test_placement_methods_of_the_drill_and_reconcile_fakes_do_not_raise() -> None:
    """F-604: no fake adapter placement method in the two old-rule files raises any more.

    Checked on the AST of `tests/test_drills.py` and `tests/test_reconcile.py`. The check is
    armed: each file must still define the two methods (a deleted fake would not pass quietly).
    """
    here = Path(__file__).parent
    for name in ("test_drills.py", "test_reconcile.py"):
        tree = ast.parse((here / name).read_text(encoding="utf-8"))
        defined: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.name not in {"place_order", "place_algo_order"}:
                continue
            defined.add(node.name)
            raises = [n.lineno for n in ast.walk(node) if isinstance(n, ast.Raise)]
            assert raises == [], f"{name}::{node.name} raises at line(s) {raises}"
        assert defined == {"place_order", "place_algo_order"}, (name, defined)


def test_no_place_order_invariant_outcome_is_retired() -> None:
    """D-27, 08-REVIEW IN-08: the outcome that encoded the old rule is retired, not renamed."""
    import src.ops.drills as drills

    retired = "no_place_order_invariant_held"
    assert not hasattr(drills, "OUTCOME_NO_PLACE_ORDER_INVARIANT")
    assert retired not in drills.ALL_OUTCOMES
    assert drills.RETIRED_OUTCOMES[retired] == (
        "encoded the pre-D034 rule (08-REVIEW IN-08); replaced by the narrowed static guard"
    )
    assert not set(drills.RETIRED_OUTCOMES) & drills.ALL_OUTCOMES
    # Removed from src: no module names the retired constant any more.
    for py_file in SRC_ROOT.rglob("*.py"):
        assert "OUTCOME_NO_PLACE_ORDER_INVARIANT" not in py_file.read_text(encoding="utf-8")
    # A DrillOutcome carrying the retired string is refused.
    with pytest.raises(ValueError, match="unknown outcome"):
        drills.DrillOutcome(
            drill="unprotected", fault="x", outcome=retired, occurred_at_utc=DRILL_NOW
        )


def test_safe_mode_blocked_outcome_is_emitted_by_the_entry_guard_drills() -> None:
    """D-27: OUTCOME_SAFE_MODE_BLOCKED was never emitted before; two drills emit it now."""
    from src.ops.drills import OUTCOME_SAFE_MODE_BLOCKED, DrillLog, run_all_drills

    outcomes = run_all_drills(
        _build_all_drill_declarations(now_utc=DRILL_NOW),
        journal=DrillLog(),
        now_utc_sequence=_build_now_utc_sequence(DRILL_NOW),
    )
    blocked = sorted(o.drill for o in outcomes if o.outcome == OUTCOME_SAFE_MODE_BLOCKED)
    assert blocked == ["stale_feed", "unprotected"]


# --------------------------------------------------------------------------- #
# Phase 20 drills (plan 20-23, D-27, D-28, G2-016).
# --------------------------------------------------------------------------- #


def test_unprotected_drill_blocks_entries_through_the_loop() -> None:
    """D-27: UNPROTECTED runs one real ReconcileLoop tick (F-604: the loop places nothing)."""
    from src.ops.drills import OUTCOME_SAFE_MODE_BLOCKED, DrillLog, run_drill

    rig = _build_unprotected_rig()
    placements = record_placements(rig.adapter)
    from src.ops.drills import make_unprotected_drill

    drill = make_unprotected_drill(
        loop=rig.loop, safe_mode_controller=rig.safe_mode, now_utc=DRILL_NOW
    )

    outcome = run_drill(drill, journal=DrillLog(), now_utc=DRILL_NOW)

    assert outcome.outcome == OUTCOME_SAFE_MODE_BLOCKED
    assert rig.safe_mode.in_safe_mode is True
    assert rig.safe_mode.entered_reason == "POSITION_WITHOUT_STOP"
    assert rig.protection.notified == [(PLAN_H, "POSITION_WITHOUT_STOP")]
    verdict = rig.safe_mode.guard_new_entries(trade_plan=None)
    assert verdict.is_no_trade is True
    assert verdict.reason_code == "RECONCILIATION_REQUIRED"
    by_reason = {a.reason: a for a in rig.alerts.alerts}
    assert by_reason["POSITION_WITHOUT_STOP"].event == "UNPROTECTED_POSITION"
    assert by_reason["POSITION_WITHOUT_STOP"].plan_hash == PLAN_H
    # The reconcile path placed and cancelled nothing.
    assert placements == []
    assert rig.adapter.forbidden_calls == []
    assert rig.adapter.cancelled_algo == [] and rig.adapter.cancelled_normal == []


def test_unprotected_drill_fails_when_the_scenario_has_no_divergence() -> None:
    """A drill whose injected fault never shows up must fail, not pass."""
    from src.ops.drills import DrillLog, make_unprotected_drill, run_drill

    plan = make_plan_protection(PLAN_H, symbol="BTCUSDT", state="PROTECTED")
    stop = make_algo_order(
        derive_algo_client_id(plan_hash=PLAN_H, role=OrderRole.STOP_LOSS.value), "BTCUSDT"
    )
    rig = build_rig(plans=(plan,), algo=(stop,), positions=(make_position("BTCUSDT", "0.004"),))
    drill = make_unprotected_drill(
        loop=rig.loop, safe_mode_controller=rig.safe_mode, now_utc=DRILL_NOW
    )
    with pytest.raises(AssertionError, match="POSITION_WITHOUT_STOP"):
        run_drill(drill, journal=DrillLog(), now_utc=DRILL_NOW)


def test_stale_feed_drill_enters_safe_mode_through_the_loops_feed_check() -> None:
    """D-25, D-27: a stale mark price is judged by the loop: STALE_FEED, STALE_DATA, blocked."""
    from src.ops.drills import (
        OUTCOME_SAFE_MODE_BLOCKED,
        DrillLog,
        make_stale_feed_drill,
        run_drill,
    )

    rig = _build_stale_feed_rig()
    placements = record_placements(rig.adapter)
    drill = make_stale_feed_drill(
        loop=rig.loop, safe_mode_controller=rig.safe_mode, now_utc=DRILL_NOW
    )

    outcome = run_drill(drill, journal=DrillLog(), now_utc=DRILL_NOW)

    assert outcome.outcome == OUTCOME_SAFE_MODE_BLOCKED
    assert rig.safe_mode.in_safe_mode is True
    assert rig.safe_mode.entered_reason == "STALE_FEED"
    assert [(a.event, a.subject, a.reason) for a in rig.alerts.alerts] == [
        ("STALE_DATA", "BTCUSDT", "MARK_PRICE_STALE")
    ]
    assert rig.feed is not None and rig.feed.calls == 1
    verdict = rig.safe_mode.guard_new_entries(trade_plan=None)
    assert (verdict.is_no_trade, verdict.reason_code) == (True, "RECONCILIATION_REQUIRED")
    assert placements == [] and rig.adapter.forbidden_calls == []


def test_stale_feed_drill_fails_when_the_feed_is_fresh() -> None:
    from src.ops.drills import DrillLog, make_stale_feed_drill, run_drill

    rig = _build_stale_feed_rig(stale=False)
    drill = make_stale_feed_drill(
        loop=rig.loop, safe_mode_controller=rig.safe_mode, now_utc=DRILL_NOW
    )
    with pytest.raises(AssertionError, match="judge a feed stale"):
        run_drill(drill, journal=DrillLog(), now_utc=DRILL_NOW)
    assert rig.safe_mode.in_safe_mode is False


def _phases_of(journal: RecordingJournal, identifier: str) -> list[str]:
    return [
        json.loads(e.payload_json)["phase"] for e in journal.events if e.entity_id == identifier
    ]


def test_manual_close_drill_orphan_variant_sweeps_the_legs_that_stayed() -> None:
    """D-28, G4-035 answer (b): the position was closed outside, the legs stay as orphans.

    The control keeps the legs (the entry filled, so it is not terminal), enters SAFE_MODE
    MANUAL_CLOSE; the sweeper then cancels each leg after two zero reads and verifies it.
    """
    from src.ops.drills import OUTCOME_ORPHAN_SWEPTED, DrillLog, run_drill

    wiring = _build_manual_close_wiring(now_utc=DRILL_NOW, position_open=False)

    outcome = run_drill(wiring.declaration, journal=DrillLog(), now_utc=DRILL_NOW)

    assert outcome.outcome == OUTCOME_ORPHAN_SWEPTED
    exchange = wiring.exchange
    assert exchange.open_algos == {}
    assert len(exchange.calls_to("cancel_algo_order")) == 3
    legs = _manual_leg_ids()
    for client_algo_id in legs.values():
        assert _phases_of(wiring.journal, client_algo_id) == ["pre_cancel", "post_cancel"]
    kept = [
        json.loads(e.payload_json)
        for e in wiring.journal.events
        if e.event_type == "PROTECTIVES_KEPT"
    ]
    assert [k["reason_code"] for k in kept] == ["ENTRY_NOT_TERMINAL"]
    assert wiring.enablement.disabled is True
    assert wiring.controller.in_safe_mode is True
    assert wiring.controller.entered_reason == "MANUAL_CLOSE"
    assert wiring.placements == []


def test_manual_close_drill_auto_cancel_variant_has_nothing_to_sweep() -> None:
    """D-28, G4-035 answer (a): the exchange removed the closePosition legs with the position."""
    from src.ops.drills import OUTCOME_SAFE_MODE_ENTERED, DrillLog, run_drill

    wiring = _build_manual_close_wiring(
        now_utc=DRILL_NOW, position_open=False, legs_auto_cancelled=True
    )

    outcome = run_drill(wiring.declaration, journal=DrillLog(), now_utc=DRILL_NOW)

    assert outcome.outcome == OUTCOME_SAFE_MODE_ENTERED
    assert wiring.exchange.calls_to("cancel_algo_order") == []  # nothing left to cancel
    assert wiring.controller.in_safe_mode is True
    assert wiring.controller.entered_reason == "MANUAL_CLOSE"
    assert [
        e for e in wiring.journal.events if e.event_type == "MANUAL_CLOSE_ORPHAN_UNVERIFIED"
    ] == []
    assert wiring.placements == []


def test_manual_close_drill_with_the_position_still_open_never_cancels_the_stop() -> None:
    """D-09, RISK-03: the position is still open, so no leg is cancelled by the control or the
    sweeper; the drill ends with SAFE_MODE MANUAL_CLOSE and the stop in place."""
    from src.ops.drills import OUTCOME_SAFE_MODE_ENTERED, DrillLog, run_drill

    wiring = _build_manual_close_wiring(now_utc=DRILL_NOW, position_open=True)
    stop_id = _manual_leg_ids()["STOP_LOSS"]

    outcome = run_drill(wiring.declaration, journal=DrillLog(), now_utc=DRILL_NOW)

    assert outcome.outcome == OUTCOME_SAFE_MODE_ENTERED
    assert stop_id in wiring.exchange.open_algos
    assert set(wiring.exchange.open_algos) == set(_manual_leg_ids().values())
    assert wiring.exchange.calls_to("cancel_algo_order") == []
    assert wiring.exchange.positions[MANUAL_SYMBOL] == MANUAL_QUANTITY
    kept = [
        json.loads(e.payload_json)
        for e in wiring.journal.events
        if e.event_type == "PROTECTIVES_KEPT"
    ]
    assert [k["reason_code"] for k in kept] == ["FIRST_READ_NONZERO"]


def test_loop_drills_never_exit_safe_mode() -> None:
    """D-15: none of the Phase 20 drills exits SAFE_MODE; the restore drill alone does, through
    the operator exit (`test_the_restore_drill_exits_with_an_operator_id` pins the operator id)."""
    from src.ops.drills import DrillLog, run_all_drills

    declarations = _build_all_drill_declarations(now_utc=DRILL_NOW)
    run_all_drills(
        declarations,
        journal=DrillLog(),
        now_utc_sequence=_build_now_utc_sequence(DRILL_NOW),
    )
    for rig in BUILT_LOOP_RIGS:
        assert rig.safe_mode.in_safe_mode is True
    assert BUILT_MANUAL_CLOSE[0].controller.in_safe_mode is True


# --------------------------------------------------------------------------- #
# Test 5 — SAFE_MODE exit is rehearsed only through the restore path.
# --------------------------------------------------------------------------- #


def test_safe_mode_exit_only_via_restore_drill() -> None:
    """Beh. 5: SAFE_MODE exit is rehearsed only through the restore
    drill (Pitfall 4: a boolean flip without both a clean compare
    AND a journaled restore event is rejected).

    The restore drill enters SAFE_MODE on a stale compare, then
    exercises the exit path with a clean compare and asserts the
    controller returns to NORMAL. No other drill exits SAFE_MODE.
    """
    from src.ops.drills import (
        DrillLog,
        run_all_drills,
    )

    base = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)
    now_utc_sequence = _build_now_utc_sequence(base)
    declarations = _build_all_drill_declarations(now_utc=base)
    journal = DrillLog()

    outcomes = run_all_drills(
        declarations,
        journal=journal,
        now_utc_sequence=now_utc_sequence,
    )

    # The restore drill is the only one that exits SAFE_MODE.
    restore_outcome = next(o for o in outcomes if o.drill == "restore")
    assert restore_outcome.outcome == "restore_clean_exit"

    # Every other drill either enters SAFE_MODE or sweeps an orphan
    # (which also enters SAFE_MODE on the divergence). None of them
    # exit SAFE_MODE.
    for outcome in outcomes:
        if outcome.drill == "restore":
            continue
        assert outcome.outcome in {
            "safe_mode_entered",
            "safe_mode_blocked_entries",
            "orphan_swept",
            "replay_one_transition",
        }, (
            f"drill {outcome.drill!r}: unexpected outcome "
            f"{outcome.outcome!r} (only restore exits SAFE_MODE)"
        )


# --------------------------------------------------------------------------- #
# Test 6 — the harness rejects malformed inputs.
# --------------------------------------------------------------------------- #


def test_run_drill_rejects_naive_now_utc() -> None:
    """Beh. 6: the harness rejects naive `now_utc` datetimes (D-12).

    A naive datetime would silently break the journal_event_id
    derivation (which uses `int(now_utc.timestamp() * 1000)`) and
    the UTC-aware validation in JournalEvent. The harness fails
    closed.
    """
    from src.ops.drills import (
        DRILL_UNPROTECTED,
        DrillDeclaration,
        DrillLog,
        run_drill,
    )

    def _inject() -> str:
        return "test fault"

    def _assert(journal: DrillLog, context: dict[str, Any]) -> str:
        return "safe_mode_entered"

    declaration = DrillDeclaration(
        name=DRILL_UNPROTECTED,
        runbook_section="test",
        inject=_inject,
        assert_outcome=_assert,
    )
    journal = DrillLog()
    naive = datetime(2026, 9, 19, 12, 0, 0)  # no tzinfo
    with pytest.raises(ValueError, match="UTC-aware"):
        run_drill(declaration, journal=journal, now_utc=naive)


def test_run_all_drills_rejects_wrong_count() -> None:
    """Beh. 7: `run_all_drills` rejects a declaration count that
    doesn't match the canonical 8-drill vocabulary.

    A missing drill or a duplicate name would silently corrupt the
    acceptance artifact. The harness fails closed.
    """
    from src.ops.drills import (
        DRILL_UNPROTECTED,
        DrillDeclaration,
        DrillLog,
        run_all_drills,
    )

    def _inject() -> str:
        return "test fault"

    def _assert(journal: DrillLog, context: dict[str, Any]) -> str:
        return "safe_mode_entered"

    declaration = DrillDeclaration(
        name=DRILL_UNPROTECTED,
        runbook_section="test",
        inject=_inject,
        assert_outcome=_assert,
    )
    journal = DrillLog()
    base = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="expected 8 declarations"):
        run_all_drills(
            (declaration,),
            journal=journal,
            now_utc_sequence=(base,),
        )


# --------------------------------------------------------------------------- #
# Static guard — the drill harness never imports or invokes a
# place-order path on any module under src/ops/.
# --------------------------------------------------------------------------- #


def test_no_place_order_path_in_src_ops() -> None:
    """Static guard: src/ops/ must not import or call any
    Binance SDK place-order method. The drill harness is the LAST
    line of defense against stale protective orders, but it must
    NEVER initiate one (D-03 + EXEC-02 acceptance proof)."""
    from pathlib import Path

    src_root = Path(__file__).parent.parent / "src" / "ops"
    if not src_root.exists():
        pytest.skip("src/ops/ not yet created")
    forbidden = ("new_order", "new_algo_order", "place_order", "place_algo_order")
    for py_file in src_root.glob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for token in forbidden:
            # Allow the token in comments / docstrings / constant
            # names that describe the invariant (e.g.,
            # "OUTCOME_NO_PLACE_ORDER_INVARIANT" or "must never place
            # a new order"). The runtime check is the caller-module record of the fakes'
            # placement methods (F-604, plan 20-23); this guard is the source-level rule.
            if token in text:
                lines_with_token = [line for line in text.splitlines() if token in line]
                for line in lines_with_token:
                    stripped = line.strip()
                    # Allow comments and docstrings.
                    if stripped.startswith("#") or '"""' in line or "'''" in line:
                        continue
                    # Allow constant names like OUTCOME_NO_PLACE_ORDER_INVARIANT.
                    if (
                        "OUTCOME_" in line
                        or "no_place_order" in line
                        or "PLACE_ORDER_INVARIANT" in line
                    ):
                        continue
                    # Allow a fake adapter's place_order method definition.
                    if "def place_order" in line or "def place_algo_order" in line:
                        continue
                    pytest.fail(
                        f"{py_file} contains forbidden place-order token "
                        f"{token!r} in non-comment line: {line!r}"
                    )


def test_no_binance_sdk_import_in_src_ops() -> None:
    """Static guard: src/ops/ must not import the Binance SDK.
    The drill harness consumes Protocol-typed adapters; only the
    adapter itself imports the SDK (RESEARCH §Pattern 1, BINANCE.md §2)."""
    from pathlib import Path

    src_root = Path(__file__).parent.parent / "src" / "ops"
    if not src_root.exists():
        pytest.skip("src/ops/ not yet created")
    forbidden = ("binance_sdk", "from binance")
    for py_file in src_root.glob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{py_file} contains forbidden Binance SDK import {token!r}"
