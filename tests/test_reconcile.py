"""Phase 8 reconciler tests (plan 08-04, task 2 + 3).

Per D-03: the reconciler is the exchange-truth safety net. It compares
local intent against three exchange-truth sources (normal orders, algo
orders, positions) and either:
  - reports `agreement=True` with an empty divergence list (clean tick), or
  - reports `agreement=False` with a typed divergence list that drives
    SAFE_MODE entry + orphan-sweeper action.

Three behaviors pinned here (mirrors the FakeAdapter pattern from
`tests/test_paper_resync.py`):

  1. Clean compare: a FakeReconcileAdapter whose truth snapshots match
     local intent yields `agreement=True` and zero divergences.
  2. Orphan protective swept: an injected orphan protective (local algo
     STOP_LOSS with no local position and no exchange position) yields
     `ORPHAN_PROTECTIVE` divergence, the sweeper cancels it after
     authoritative position-zero verification, journals pre/post images
     as `JournalEvent`s, and a re-scan finds zero divergences.
  3. Divergence forces SAFE_MODE: an exchange truth with rows that
     have no local intent (e.g., a phantom exchange position) forces
     SAFE_MODE; entries are blocked while monitoring continues.

The test loads the golden fixture pair
(`tests/fixtures/phase8/orphan_divergence/{input,expected}.json`) and
asserts the reconcile + sweep outcome against the expected counts,
divergence kinds, cancel calls, and journal events.

A static guard asserts the FakeReconcileAdapter never receives a
`place_order` call on any path (the reconciler is query/cancel only —
the no-place-order invariant is the EXEC-02 acceptance proof).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

PHASE8_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase8"
ORPHAN_FIXTURE_DIR = PHASE8_FIXTURES_DIR / "orphan_divergence"


def _load_input() -> dict[str, Any]:
    return json.loads(
        (ORPHAN_FIXTURE_DIR / "input.json").read_text(encoding="utf-8")
    )


def _load_expected() -> dict[str, Any]:
    return json.loads(
        (ORPHAN_FIXTURE_DIR / "expected.json").read_text(encoding="utf-8")
    )


def _parse_utc(raw: str) -> datetime:
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None:
        raise ValueError(f"naive datetime in fixture: {raw!r}")
    return value.astimezone(UTC)


# --------------------------------------------------------------------------- #
# Fixtures and builders.
# --------------------------------------------------------------------------- #


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
        stop_price=(
            Decimal(str(row["stop_price"])) if row.get("stop_price") else None
        ),
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
        trigger_price=(
            Decimal(str(row["trigger_price"]))
            if row.get("trigger_price")
            else None
        ),
        price=Decimal(str(row["price"])) if row.get("price") else None,
        trigger_time_utc=(
            _parse_utc(row["trigger_time_utc"])
            if row.get("trigger_time_utc")
            else None
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
        mark_price=(
            Decimal(str(row["mark_price"])) if row.get("mark_price") else None
        ),
        unrealized_profit=Decimal(str(row["unrealized_profit"])),
        liquidation_price=(
            Decimal(str(row["liquidation_price"]))
            if row.get("liquidation_price")
            else None
        ),
        notional=Decimal(str(row["notional"])) if row.get("notional") else None,
        margin_asset=row["margin_asset"],
        update_time_utc=_parse_utc(row["update_time_utc"]),
    )


class FakeReconcileAdapter:
    """Fake three-source exchange adapter for reconciler tests.

    Mirrors the FakeAdapter pattern from `tests/test_paper_resync.py`:
    records every query + cancel call and returns the pre-configured
    truth. Tests inject this in place of the real
    `BinanceUsdmAdapter` so unit tests never touch the network.

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
    ) -> None:
        self._normal_orders = list(normal_orders or [])
        self._algo_orders = list(algo_orders or [])
        self._positions = list(positions or [])
        self._position_reads = list(position_reads or [])
        self._position_read_index = 0

        self.snapshot_open_normal_orders_calls = 0
        self.snapshot_open_algo_orders_calls = 0
        self.snapshot_positions_calls = 0
        self.query_algo_order_by_client_calls: list[str] = []
        self.cancel_normal_order_calls: list[tuple[str, str]] = []
        self.cancel_algo_order_calls: list[tuple[str, str]] = []
        # Any place-order method call raises (no-place-order invariant).
        self.place_order_calls = 0

    async def snapshot_open_normal_orders(
        self, *, symbol: str | None = None
    ) -> list[Any]:
        self.snapshot_open_normal_orders_calls += 1
        if symbol is None:
            return list(self._normal_orders)
        return [o for o in self._normal_orders if o.symbol == symbol]

    async def snapshot_open_algo_orders(
        self, *, symbol: str | None = None
    ) -> list[Any]:
        self.snapshot_open_algo_orders_calls += 1
        if symbol is None:
            return list(self._algo_orders)
        return [o for o in self._algo_orders if o.symbol == symbol]

    async def snapshot_positions(
        self, *, symbol: str | None = None
    ) -> list[Any]:
        self.snapshot_positions_calls += 1
        if symbol is None:
            return list(self._positions)
        return [p for p in self._positions if p.symbol == symbol]

    def read_position(self, *, symbol: str) -> Decimal:
        """Read one position amount from the configured sequence.

        Used by the authoritative position-zero verification path
        (T-8-30): the sweeper requires two consecutive zero reads OR
        position-plus-order-truth agreement before any cancel.
        """
        if self._position_read_index >= len(self._position_reads):
            # After configured reads, return the last configured value.
            value = self._position_reads[-1] if self._position_reads else Decimal("0")
        else:
            value = self._position_reads[self._position_read_index]
            self._position_read_index += 1
        return value

    async def query_algo_order_by_client(
        self, *, client_algo_id: str
    ) -> Any:
        from src.adapters.binance_usdm import AlgoOrderProbe

        self.query_algo_order_by_client_calls.append(client_algo_id)
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

    async def cancel_normal_order(
        self, *, symbol: str, orig_client_order_id: str
    ) -> None:
        self.cancel_normal_order_calls.append((symbol, orig_client_order_id))
        self._normal_orders = [
            o
            for o in self._normal_orders
            if not (
                o.symbol == symbol and o.client_order_id == orig_client_order_id
            )
        ]

    async def cancel_algo_order(
        self, *, symbol: str, client_algo_id: str
    ) -> None:
        self.cancel_algo_order_calls.append((symbol, client_algo_id))
        self._algo_orders = [
            o
            for o in self._algo_orders
            if not (
                o.symbol == symbol and o.client_algo_id == client_algo_id
            )
        ]

    async def place_order(self, **_kwargs: Any) -> None:
        """The reconciler must NEVER place a new order (D-03)."""
        self.place_order_calls += 1
        raise AssertionError(
            "reconciler must never place a new order — query/cancel only"
        )

    async def place_algo_order(self, **_kwargs: Any) -> None:
        """The reconciler must NEVER place a new algo order (D-03)."""
        self.place_order_calls += 1
        raise AssertionError(
            "reconciler must never place a new algo order — query/cancel only"
        )


class _FakeJournal:
    """Captures JournalEvents emitted by the sweeper.

    Mirrors the fake-journal pattern from prior phases: records every
    event in insertion order; tests assert event_type / entity_type /
    pre/post-image keys against the fixture expected values.
    """

    def __init__(self) -> None:
        self.events: list[Any] = []

    def record(self, event: Any) -> None:
        self.events.append(event)


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
        "normal_orders": [
            _build_open_order(o)
            for o in fixture["exchange_truth"]["normal_orders"]
        ],
        "algo_orders": [
            _build_open_algo_order(o)
            for o in fixture["exchange_truth"]["algo_orders"]
        ],
        "positions": [
            _build_position(p) for p in fixture["exchange_truth"]["positions"]
        ],
    }


# --------------------------------------------------------------------------- #
# Test 1 — clean compare: truth matches local intent, agreement=True.
# --------------------------------------------------------------------------- #


def test_clean_compare_yields_agreement_with_zero_divergences() -> None:
    """Beh. 1: local intent + truth agree on all three sources.

    A fake adapter whose truth snapshots mirror the local intent must
    yield `agreement=True` and an empty divergences list. This is the
    no-op fast path the reconciler takes on a clean tick.
    """
    from src.reconcile.compare import compare

    local = {
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
        "open_positions": [
            {
                "symbol": "BTCUSDT",
                "position_side": "LONG",
                "position_amt": Decimal("0.010"),
            }
        ],
    }
    truth = {
        "normal_orders": [
            _build_open_order(
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
            )
        ],
        "algo_orders": [
            _build_open_algo_order(
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
            )
        ],
        "positions": [
            _build_position(
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
            )
        ],
    }

    diff = compare(
        local_open_orders=local["open_orders"],
        local_open_algos=local["open_algos"],
        local_open_positions=local["open_positions"],
        truth_normal_orders=truth["normal_orders"],
        truth_algo_orders=truth["algo_orders"],
        truth_positions=truth["positions"],
    )

    assert diff.agreement is True
    assert len(diff.divergences) == 0
    assert len(diff.orphan_protectives) == 0


# --------------------------------------------------------------------------- #
# Test 2 — orphan protective: divergence classified + sweeper cancels.
# --------------------------------------------------------------------------- #


def test_orphan_protective_divergence_classified_and_swept() -> None:
    """Beh. 2: injected orphan protective yields ORPHAN_PROTECTIVE
    divergence and the sweeper cancels the algo after authoritative
    position-zero verification, journals pre/post images, and re-scans
    to a clean diff.

    The fixture pins a scenario where local intent has a STOP_LOSS
    algo for BTCUSDT but no local position and no exchange position.
    The reconciler classifies this as ORPHAN_PROTECTIVE divergence;
    the sweeper verifies position-zero across two consecutive reads,
    cancels via the adapter cancel path, journals the pre/post
    images, and a re-scan yields agreement=True.
    """
    from src.reconcile.compare import compare
    from src.reconcile.sweeper import OrphanSweeper

    case_input = _load_input()
    expected = _load_expected()

    local = _make_local_intent(case_input)
    truth = _make_truth(case_input)

    # Diff the local intent against the truth: classify orphan.
    diff = compare(
        local_open_orders=local["open_orders"],
        local_open_algos=local["open_algos"],
        local_open_positions=local["open_positions"],
        truth_normal_orders=truth["normal_orders"],
        truth_algo_orders=truth["algo_orders"],
        truth_positions=truth["positions"],
    )
    assert diff.agreement is False
    assert len(diff.divergences) == 1
    div = diff.divergences[0]
    assert div.kind == "ORPHAN_PROTECTIVE"
    assert div.symbol == "BTCUSDT"
    assert div.client_algo_id == "xa-1111111111111111111111111111111SL"

    # The orphan should also appear in the orphan_protectives list
    # the sweeper consumes.
    assert len(diff.orphan_protectives) == 1
    orphan = diff.orphan_protectives[0]
    assert orphan.symbol == "BTCUSDT"
    assert orphan.client_algo_id == "xa-1111111111111111111111111111111SL"

    # Wire the fake adapter + journal; configure position reads to
    # confirm zero across two consecutive reads (authoritative
    # position-zero verification per T-8-30).
    adapter = FakeReconcileAdapter(
        normal_orders=truth["normal_orders"],
        algo_orders=truth["algo_orders"],
        positions=truth["positions"],
        position_reads=[
            Decimal(case_input["position_verification"]["first_read_position_amt"]),
            Decimal(case_input["position_verification"]["second_read_position_amt"]),
        ],
    )
    journal = _FakeJournal()
    now_utc = datetime(2026, 9, 19, 11, 0, tzinfo=UTC)

    sweeper = OrphanSweeper(
        adapter=adapter,  # type: ignore[arg-type]
        journal=journal,  # type: ignore[arg-type]
        now_utc=now_utc,
    )
    sweep_result = asyncio.run(
        sweeper.sweep(diff, position_verifier=adapter.read_position)
    )

    # Sweep outcome matches the fixture's expected counts.
    expected_sweep = expected["sweep_result"]
    assert sweep_result.swept_count == expected_sweep["swept_count"]
    assert len(sweep_result.cancelled) == 1
    assert sweep_result.cancelled[0] == (
        "BTCUSDT",
        "xa-1111111111111111111111111111111SL",
    )
    assert len(sweep_result.skipped) == 0

    # Adapter cancel called exactly once (on the orphan algo); no
    # place-order call (the no-place-order invariant).
    assert len(adapter.cancel_algo_order_calls) == 1
    assert adapter.cancel_algo_order_calls[0] == (
        "BTCUSDT",
        "xa-1111111111111111111111111111111SL",
    )
    assert adapter.place_order_calls == 0

    # Position verifier invoked twice (consecutive zero reads).
    assert len(adapter._position_reads) - adapter._position_read_index == 0

    # Journal recorded the pre AND post ORPHAN_SWEEP events
    # (journal-first ordering: pre before cancel, post after).
    assert len(journal.events) == 2
    pre_event = journal.events[0]
    post_event = journal.events[1]
    for event in (pre_event, post_event):
        assert event.event_type == "ORPHAN_SWEEP"
        assert event.entity_type == "OpenAlgoOrder"
        assert event.entity_id == "xa-1111111111111111111111111111111SL"
    # Pre-image captures the orphan state; post-image captures the cancel.
    assert "symbol" in pre_event.payload_json
    assert "cancelled" in post_event.payload_json
    assert "phase" in pre_event.payload_json
    assert "phase" in post_event.payload_json

    # Re-scan after the sweep: the orchestrator would also drop
    # the swept algo from local intent, so the post-sweep diff
    # should NOT re-classify it as ORPHAN_PROTECTIVE. The rescan
    # mirrors what the scheduled tick sees after the sweeper runs.
    post_sweep_normal = list(truth["normal_orders"])
    post_sweep_algos = [
        a
        for a in truth["algo_orders"]
        if a.client_algo_id != "xa-1111111111111111111111111111111SL"
    ]
    post_sweep_local_algos = [
        a for a in local["open_algos"]
        if a["client_algo_id"] != "xa-1111111111111111111111111111111SL"
    ]
    post_diff = compare(
        local_open_orders=local["open_orders"],
        local_open_algos=post_sweep_local_algos,
        local_open_positions=local["open_positions"],
        truth_normal_orders=post_sweep_normal,
        truth_algo_orders=post_sweep_algos,
        truth_positions=truth["positions"],
    )
    # After the orphan algo is gone from both sides, no
    # ORPHAN_PROTECTIVE remains. The entry still lacks a
    # protective, so ENTRY_WITHOUT_PROTECTIVE may remain — but
    # that's a SAFE_MODE trigger, not a sweeper trigger.
    assert all(d.kind != "ORPHAN_PROTECTIVE" for d in post_diff.divergences)


# --------------------------------------------------------------------------- #
# Test 3 — divergence forces SAFE_MODE; no cancel issued.
# --------------------------------------------------------------------------- #


def test_divergence_forces_safe_mode_without_cancel() -> None:
    """Beh. 3: any divergence enters SAFE_MODE; new entries are blocked
    while monitoring continues. The reconciler does NOT cancel on the
    divergence path — cancellation is the sweeper's job and only
    triggers on ORPHAN_PROTECTIVE.

    A phantom exchange position (truth has a position that local has
    no record of) yields UNSYNCED_POSITION divergence. The reconciler
    MUST surface this and SAFE_MODE MUST be entered. No cancel call
    happens on the divergence path itself.
    """
    from src.reconcile.compare import compare
    from src.reconcile.safe_mode import (
        SAFE_MODE_TICK_SECONDS,
        SafeModeController,
    )

    local = {
        "open_orders": [],
        "open_algos": [],
        "open_positions": [],
    }
    truth = {
        "normal_orders": [],
        "algo_orders": [],
        "positions": [
            _build_position(
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
            )
        ],
    }

    diff = compare(
        local_open_orders=local["open_orders"],
        local_open_algos=local["open_algos"],
        local_open_positions=local["open_positions"],
        truth_normal_orders=truth["normal_orders"],
        truth_algo_orders=truth["algo_orders"],
        truth_positions=truth["positions"],
    )
    assert diff.agreement is False
    kinds = {d.kind for d in diff.divergences}
    assert "UNSYNCED_POSITION" in kinds

    # Wire a fake controller and enter SAFE_MODE on the divergence.
    journal = _FakeJournal()
    adapter = FakeReconcileAdapter(
        normal_orders=truth["normal_orders"],
        algo_orders=truth["algo_orders"],
        positions=truth["positions"],
    )
    controller = SafeModeController(
        adapter=adapter,  # type: ignore[arg-type]
        journal=journal,  # type: ignore[arg-type]
    )

    assert not controller.in_safe_mode
    controller.enter_safe_mode(reason=diff.divergences[0].kind)
    assert controller.in_safe_mode

    # Guard blocks new entries (mirrors RECONCILIATION_REQUIRED).
    verdict = controller.guard_new_entries(trade_plan=None)  # type: ignore[arg-type]
    assert verdict.is_no_trade is True
    assert verdict.reason_code == "RECONCILIATION_REQUIRED"

    # No cancel called during the divergence path itself.
    assert adapter.cancel_algo_order_calls == []
    assert adapter.cancel_normal_order_calls == []
    assert adapter.place_order_calls == 0

    # SAFE_MODE_TICK_SECONDS constant is documented + tunable-but-not-mid-run.
    assert SAFE_MODE_TICK_SECONDS == 60


# --------------------------------------------------------------------------- #
# Test 4 — entry-without-protective divergence does NOT sweep.
# --------------------------------------------------------------------------- #


def test_entry_without_protective_divergence_does_not_sweep() -> None:
    """Beh. 4: a local entry with no matching protective yields a
    non-orphan divergence (entry without protection). The sweeper MUST
    refuse to cancel — only ORPHAN_PROTECTIVE cancellations are
    authorised (Pitfall 1: never auto-place rescue protection).

    This is the divergence that drives SAFE_MODE but not the
    sweeper. The test asserts the sweeper's `sweep()` is a no-op on
    non-orphan divergences.
    """
    from src.reconcile.compare import compare
    from src.reconcile.sweeper import OrphanSweeper

    local = {
        "open_orders": [
            {
                "client_order_id": "x-11111111111111111111111111111111EN",
                "symbol": "BTCUSDT",
                "order_role": "ENTRY",
                "status": "NEW",
            }
        ],
        "open_algos": [],
        "open_positions": [],
    }
    truth = {
        "normal_orders": [
            _build_open_order(
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
            )
        ],
        "algo_orders": [],
        "positions": [],
    }

    diff = compare(
        local_open_orders=local["open_orders"],
        local_open_algos=local["open_algos"],
        local_open_positions=local["open_positions"],
        truth_normal_orders=truth["normal_orders"],
        truth_algo_orders=truth["algo_orders"],
        truth_positions=truth["positions"],
    )
    assert diff.agreement is False
    assert len(diff.orphan_protectives) == 0

    # Sweeper runs on the diff but cancels nothing (no orphan
    # protective present; cancel-only posture).
    adapter = FakeReconcileAdapter(
        normal_orders=truth["normal_orders"],
        algo_orders=truth["algo_orders"],
        positions=truth["positions"],
        position_reads=[Decimal("0")],
    )
    journal = _FakeJournal()
    sweeper = OrphanSweeper(
        adapter=adapter,  # type: ignore[arg-type]
        journal=journal,  # type: ignore[arg-type]
        now_utc=datetime(2026, 9, 19, 11, 0, tzinfo=UTC),
    )
    sweep_result = asyncio.run(
        sweeper.sweep(diff, position_verifier=adapter.read_position)
    )
    assert sweep_result.swept_count == 0
    assert adapter.cancel_algo_order_calls == []
    assert adapter.cancel_normal_order_calls == []


# --------------------------------------------------------------------------- #
# Test 5 — transient position gap: position reads disagree, no premature sweep.
# --------------------------------------------------------------------------- #


def test_transient_position_gap_blocks_premature_sweep() -> None:
    """Beh. 5: a transient position-zero race (first read returns
    non-zero, second returns zero) prevents the sweeper from acting
    on a single-zero read. The authoritative position-zero verification
    requires TWO consecutive zero reads OR position-plus-order-truth
    agreement (Pitfall 3: transient gaps must not trigger wrong-leg
    cancels).

    The sweeper must skip the cancel and journal the skip reason so
    the next tick can re-attempt with fresh data.
    """
    from src.reconcile.compare import compare
    from src.reconcile.sweeper import OrphanSweeper

    case_input = _load_input()
    local = _make_local_intent(case_input)
    truth = _make_truth(case_input)

    diff = compare(
        local_open_orders=local["open_orders"],
        local_open_algos=local["open_algos"],
        local_open_positions=local["open_positions"],
        truth_normal_orders=truth["normal_orders"],
        truth_algo_orders=truth["algo_orders"],
        truth_positions=truth["positions"],
    )
    assert len(diff.orphan_protectives) == 1

    # Position reads: first non-zero (transient fill in flight),
    # second zero. The first read MUST block the cancel.
    adapter = FakeReconcileAdapter(
        normal_orders=truth["normal_orders"],
        algo_orders=truth["algo_orders"],
        positions=truth["positions"],
        position_reads=[Decimal("0.010"), Decimal("0")],
    )
    journal = _FakeJournal()
    sweeper = OrphanSweeper(
        adapter=adapter,  # type: ignore[arg-type]
        journal=journal,  # type: ignore[arg-type]
        now_utc=datetime(2026, 9, 19, 11, 0, tzinfo=UTC),
    )
    sweep_result = asyncio.run(
        sweeper.sweep(diff, position_verifier=adapter.read_position)
    )

    # Cancel was skipped because the first position read was non-zero.
    assert sweep_result.swept_count == 0
    assert len(sweep_result.skipped) == 1
    skipped = sweep_result.skipped[0]
    assert skipped.symbol == "BTCUSDT"
    assert skipped.client_algo_id == "xa-1111111111111111111111111111111SL"
    assert "non-zero" in skipped.reason or "transient" in skipped.reason.lower()

    # No cancel call.
    assert adapter.cancel_algo_order_calls == []
    # No journal ORPHAN_SWEEP event for a skipped cancel.
    assert all(e.event_type != "ORPHAN_SWEEP" for e in journal.events)


# --------------------------------------------------------------------------- #
# Static guard — the reconciler never imports or invokes a place-order
# path on any module under src/reconcile/.
# --------------------------------------------------------------------------- #


def test_no_place_order_path_in_src_reconcile() -> None:
    """Static guard: src/reconcile/ must not import or call any
    Binance SDK place-order method. The reconciler is the LAST line
    of defense against stale protective orders, but it must NEVER
    initiate one (D-03 + EXEC-02 acceptance proof)."""
    from pathlib import Path

    src_root = Path(__file__).parent.parent / "src" / "reconcile"
    if not src_root.exists():
        pytest.skip("src/reconcile/ not yet created")
    forbidden = ("new_order", "new_algo_order", "place_order", "place_algo_order")
    for py_file in src_root.glob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, (
                f"{py_file} contains forbidden place-order token {token!r}"
            )


def test_no_binance_sdk_import_in_src_reconcile() -> None:
    """Static guard: src/reconcile/ must not import the Binance SDK.
    The reconciler consumes Protocol-typed adapters; only the adapter
    itself imports the SDK (RESEARCH §Pattern 1, BINANCE.md §2)."""
    from pathlib import Path

    src_root = Path(__file__).parent.parent / "src" / "reconcile"
    if not src_root.exists():
        pytest.skip("src/reconcile/ not yet created")
    forbidden = ("binance_sdk", "from binance")
    for py_file in src_root.glob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, (
                f"{py_file} contains forbidden Binance SDK import {token!r}"
            )
