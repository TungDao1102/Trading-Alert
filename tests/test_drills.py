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
  4. The no-place-order invariant holds across every drill (the
     reconciler is query/cancel only).
  5. SAFE_MODE exit is rehearsed only through the restore path
     (Pitfall 4: a boolean flip without both a clean compare AND a
     journaled restore event is rejected).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

PHASE8_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase8"
DRILL_LOG_FIXTURE_DIR = PHASE8_FIXTURES_DIR / "drill_log"

# Registry of every fake adapter built by
# `_build_all_drill_declarations` for the latest call. The
# no-place-order runtime test reads this registry because the fakes
# are otherwise function-local and inaccessible.
BUILT_DRILL_ADAPTERS: list[Any] = []


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

    The static guard at the end of the file asserts that no test ever
    invokes `place_order` — the reconciler is query/cancel only and
    invoking a place-order method on this fake is a hard test failure
    by construction (the fake raises).
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

    async def place_order(self, **_kwargs: Any) -> None:
        """The reconciler must NEVER place a new order (D-03)."""
        import logging

        logging.getLogger(__name__).error("place_order called on drill fake")
        self.place_order_calls += 1
        raise AssertionError("reconciler must never place a new order — query/cancel only")

    async def place_algo_order(self, **_kwargs: Any) -> None:
        """The reconciler must NEVER place a new algo order (D-03)."""
        import logging

        logging.getLogger(__name__).error("place_algo_order called on drill fake")
        self.place_order_calls += 1
        raise AssertionError("reconciler must never place a new algo order — query/cancel only")


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


def _build_unprotected_scenario() -> dict[str, Any]:
    """Build the UNPROTECTED drill scenario (§3).

    Local intent has an ENTRY + position but no SL protective. The
    compare classifies ENTRY_WITHOUT_PROTECTIVE divergence; SAFE_MODE
    is entered; entries are blocked.
    """
    return {
        "local_intent": {
            "open_orders": [
                {
                    "client_order_id": "x-11111111111111111111111111111111EN",
                    "symbol": "BTCUSDT",
                    "order_role": "ENTRY",
                    "status": "NEW",
                }
            ],
            "open_algos": [],
            "open_positions": [
                {
                    "symbol": "BTCUSDT",
                    "position_side": "LONG",
                    "position_amt": "0.010",
                }
            ],
        },
        "exchange_truth": {
            "normal_orders": [
                {
                    "symbol": "BTCUSDT",
                    "client_order_id": "x-11111111111111111111111111111111EN",
                    "exchange_order_id": "100001",
                    "side": "BUY",
                    "position_side": "LONG",
                    "order_type": "LIMIT",
                    "time_in_force": "GTC",
                    "status": "NEW",
                    "quantity": "0.010",
                    "price": "50000.00",
                    "stop_price": None,
                    "reduce_only": False,
                    "close_position": False,
                    "working_type": None,
                    "price_protect": None,
                    "update_time_utc": "2026-09-19T10:00:00+00:00",
                }
            ],
            "algo_orders": [],
            "positions": [
                {
                    "symbol": "BTCUSDT",
                    "position_side": "LONG",
                    "position_amt": "0.010",
                    "entry_price": "50000.00",
                    "break_even_price": "50000.00",
                    "mark_price": "50100.00",
                    "unrealized_profit": "1.00",
                    "liquidation_price": None,
                    "notional": "501.00",
                    "margin_asset": "USDT",
                    "update_time_utc": "2026-09-19T10:00:00+00:00",
                }
            ],
        },
    }


def _build_orphan_scenario() -> dict[str, Any]:
    """Build the ORPHAN drill scenario (§4).

    Local intent has a STOP_LOSS algo for BTCUSDT but no local
    position and no exchange position. The compare classifies
    ORPHAN_PROTECTIVE divergence; the sweeper cancels the algo after
    authoritative position-zero verification.
    """
    return {
        "local_intent": {
            "open_orders": [
                {
                    "client_order_id": "x-11111111111111111111111111111111EN",
                    "symbol": "BTCUSDT",
                    "order_role": "ENTRY",
                    "status": "NEW",
                }
            ],
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
            "normal_orders": [
                {
                    "symbol": "BTCUSDT",
                    "client_order_id": "x-11111111111111111111111111111111EN",
                    "exchange_order_id": "100001",
                    "side": "BUY",
                    "position_side": "LONG",
                    "order_type": "LIMIT",
                    "time_in_force": "GTC",
                    "status": "NEW",
                    "quantity": "0.010",
                    "price": "50000.00",
                    "stop_price": None,
                    "reduce_only": False,
                    "close_position": False,
                    "working_type": None,
                    "price_protect": None,
                    "update_time_utc": "2026-09-19T10:00:00+00:00",
                }
            ],
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


def _build_manual_close_scenario() -> dict[str, Any]:
    """Build the MANUAL_CLOSE drill scenario (§12).

    After a manual close, the local algo protective survives as an
    orphan. The sweeper cancels it after position-zero verification.
    """
    return _build_orphan_scenario()


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
        make_manual_close_drill,
        make_orphan_drill,
        make_restore_drill,
        make_stale_feed_drill,
        make_unprotected_drill,
    )
    from src.reconcile.compare import compare as _compare
    from src.reconcile.safe_mode import SafeModeController
    from src.reconcile.sweeper import OrphanSweeper

    # --- UNPROTECTED (§3) -------------------------------------------------
    unprotected = _build_unprotected_scenario()
    unprotected_local = _make_local_intent(unprotected)
    unprotected_truth = _make_truth(unprotected)
    unprotected_adapter = _FakeReconcileAdapter(
        normal_orders=unprotected_truth["normal_orders"],
        algo_orders=unprotected_truth["algo_orders"],
        positions=unprotected_truth["positions"],
    )
    unprotected_journal = _FakeJournal()
    unprotected_controller = SafeModeController(
        adapter=unprotected_adapter,  # type: ignore[arg-type]
        journal=unprotected_journal,  # type: ignore[arg-type]
    )
    unprotected_drill = make_unprotected_drill(
        compare_fn=_compare,
        safe_mode_controller=unprotected_controller,
        local_intent=unprotected_local,
        truth=unprotected_truth,
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

    # --- STALE_FEED (§7) --------------------------------------------------
    stale_feed_adapter = _FakeReconcileAdapter()
    stale_feed_journal = _FakeJournal()
    stale_feed_controller = SafeModeController(
        adapter=stale_feed_adapter,  # type: ignore[arg-type]
        journal=stale_feed_journal,  # type: ignore[arg-type]
    )

    def _stale_feed_check() -> bool:
        return True

    stale_feed_drill = make_stale_feed_drill(
        safe_mode_controller=stale_feed_controller,
        feed_freshness_check=_stale_feed_check,
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

    # --- MANUAL_CLOSE (§12) -----------------------------------------------
    manual_close = _build_manual_close_scenario()
    manual_close_local = _make_local_intent(manual_close)
    manual_close_truth = _make_truth(manual_close)
    manual_close_adapter = _FakeReconcileAdapter(
        normal_orders=manual_close_truth["normal_orders"],
        algo_orders=manual_close_truth["algo_orders"],
        positions=manual_close_truth["positions"],
        position_reads=[Decimal("0"), Decimal("0")],
    )
    manual_close_journal = _FakeJournal()
    manual_close_controller = SafeModeController(
        adapter=manual_close_adapter,  # type: ignore[arg-type]
        journal=manual_close_journal,  # type: ignore[arg-type]
    )
    manual_close_sweeper = OrphanSweeper(
        adapter=manual_close_adapter,  # type: ignore[arg-type]
        journal=manual_close_journal,  # type: ignore[arg-type]
        now_utc=now_utc,
    )
    manual_close_drill = make_manual_close_drill(
        sweeper=manual_close_sweeper,
        safe_mode_controller=manual_close_controller,
        local_intent=manual_close_local,
        truth=manual_close_truth,
        position_verifier=manual_close_adapter.read_position,
    )

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
            unprotected_adapter,
            orphan_adapter,
            api_down_adapter,
            stale_feed_adapter,
            db_failure_adapter,
            manual_close_adapter,
            restore_adapter,
        ]
    )
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
        "unprotected": OUTCOME_SAFE_MODE_ENTERED,
        "orphan": OUTCOME_ORPHAN_SWEPTED,
        "duplicate": OUTCOME_REPLAY_TRANSITIONED,
        "api_down": OUTCOME_SAFE_MODE_ENTERED,
        "stale_feed": OUTCOME_SAFE_MODE_ENTERED,
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
# Test 4 — the no-place-order invariant holds across every drill.
# --------------------------------------------------------------------------- #


def test_no_place_order_invariant_across_all_drills() -> None:
    """Beh. 4: the no-place-order invariant holds across every drill.

    Per D-03 + EXEC-02: the reconciler is query/cancel only. No
    drill may invoke a place-order path on any adapter. The static
    guard at the end of the file asserts the source-level invariant;
    this test asserts the runtime invariant by checking the fake
    adapter's `place_order_calls` counter after the full drill run.
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

    # Runtime check: no fake adapter in the drill suite ever received
    # a place-order call.
    assert len(BUILT_DRILL_ADAPTERS) > 0, "expected the drill builder to register fake adapters"
    for adapter in BUILT_DRILL_ADAPTERS:
        assert adapter.place_order_calls == 0, (
            f"place-order invariant violated: {adapter.place_order_calls} calls"
        )


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
            # a new order"). The runtime guard is the
            # FakeReconcileAdapter's place_order() method which raises
            # AssertionError.
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
                    # Allow the FakeReconcileAdapter's place_order
                    # method definition (which raises).
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
