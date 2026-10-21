"""The emergency close and the last validated lot filters (Phase 20, plan 20-18; Q3, D-21).

Every scenario runs against the stateful Phase 19 fake exchange with fake lot filters, an
in-memory filter store and virtual time. Nothing sleeps and nothing touches a network. A green
test proves agreement with the fake's labelled rules, not with Binance: whether Binance accepts
a close sized on stale filters is [NOT_TESTED] (best effort, Q3).
"""

from __future__ import annotations

import ast
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.domain.exchange_errors import PreSendRefusal
from src.domain.lot_filters import LotFilters
from src.execution.constraint_snapshot import PlanConstraintSnapshot
from src.execution.emergency_close import MarketEmergencyCloser
from src.execution.lot_filter_source import LotFilterSource, LotFiltersUnavailable

from tests.support.execution_limits import test_only_execution_limits as limits_with
from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
from tests.support.lot_filter_fakes import FailingLotFilterStore, InMemoryLotFilterStore
from tests.support.protection_doubles import (
    TEST_ONLY_SYMBOL,
    RecordingAlerts,
    RecordingSafeMode,
    resting_entry_for_tests,
)
from tests.support.stream_sinks import RecordingJournal
from tests.support.virtual_time import VirtualTime

D = Decimal
SYMBOL = TEST_ONLY_SYMBOL
ENTRY_PRICE = D("60000")


def lot_filters(
    *, minimum: str = "0.001", step: str = "0.001", market_max: str = "120"
) -> LotFilters:
    """FAKE filters (TEST_ONLY numbers, not exchangeInfo)."""
    return LotFilters(
        symbol=SYMBOL,
        price_tick_size=D("0.01"),
        lot_min_quantity=D(minimum),
        lot_max_quantity=D("1000"),
        lot_step_size=D(step),
        market_lot_min_quantity=D(minimum),
        market_lot_max_quantity=D(market_max),
        market_lot_step_size=D(step),
        min_notional=D("100"),
    )


@dataclass
class FilterRig:
    fake: BinanceSemanticsFakeAdapter
    journal: RecordingJournal
    safe_mode: RecordingSafeMode
    alerts: RecordingAlerts
    clock: VirtualTime
    store: InMemoryLotFilterStore
    source: LotFilterSource
    closer: MarketEmergencyCloser

    def payloads(self) -> list[dict[str, Any]]:
        return [json.loads(e.payload_json) for e in self.journal.calls]

    def sent_quantities(self) -> list[Decimal]:
        return [c["kwargs"]["quantity"] for c in self.fake.calls_to("place_market_close")]


def make_filter_rig(
    position: Decimal,
    *,
    live: LotFilters | None = None,
    stored: LotFilters | None = None,
    stored_at: datetime | None = None,
    snapshot_for: Callable[[str], PlanConstraintSnapshot | None] | None = None,
) -> FilterRig:
    """A closer over the fake exchange holding `position`, wired to a filter source."""
    clock = VirtualTime()
    fake = BinanceSemanticsFakeAdapter(now_utc=clock.now(), enforce_flat_stop_rejection=True)
    fake._apply_position_delta(SYMBOL, position, ENTRY_PRICE)
    fake.set_lot_filters(SYMBOL, live if live is not None else lot_filters())
    store = InMemoryLotFilterStore()
    if stored is not None:
        store.upsert(stored, fetched_at_utc=stored_at or clock.now() - timedelta(hours=2))
        store.upserts.clear()
    source = LotFilterSource(
        adapter=fake, store=store, limits=limits_with(), clock=clock, snapshot_for=snapshot_for
    )
    journal = RecordingJournal()
    safe_mode = RecordingSafeMode()
    alerts = RecordingAlerts()
    closer = MarketEmergencyCloser(
        adapter=fake,
        journal=journal,
        safe_mode_controller=safe_mode,
        alert_sink=alerts,
        clock=clock,
        limits=limits_with(),
        lot_filters=source,
    )
    return FilterRig(fake, journal, safe_mode, alerts, clock, store, source, closer)


async def close(rig: FilterRig) -> bool:
    return await rig.closer.close_position(entry=resting_entry_for_tests(), reason="CLOSE_REQUIRED")


# --------------------------------------------------------------------------- #
# Task 1: the tracer.
# --------------------------------------------------------------------------- #


async def test_close_uses_stale_stored_filters_when_live_read_fails() -> None:
    fetched_at = VirtualTime().now() - timedelta(hours=2)
    rig = make_filter_rig(D("0.0045"), stored=lot_filters(), stored_at=fetched_at)
    rig.fake.fail_next("symbol_lot_filters", TimeoutError("exchangeInfo timed out"))

    await close(rig)

    # One reduce-only MARKET part, floored onto the stored step (0.0045 -> 0.004), never up.
    assert rig.sent_quantities() == [D("0.004")]
    attempts = [p for p in rig.payloads() if p.get("phase") == "pre_send"]
    assert len(attempts) == 1
    assert attempts[0]["filters_stale"] is True
    assert attempts[0]["filters_fetched_at_utc"] == fetched_at.isoformat()


async def test_a_successful_live_read_is_stored_and_the_close_is_not_stale() -> None:
    rig = make_filter_rig(D("0.004"))

    closed = await close(rig)

    assert closed is True
    assert rig.sent_quantities() == [D("0.004")]
    stored = rig.store.get(SYMBOL)
    assert stored is not None
    assert stored.fetched_at_utc == rig.clock.now()
    assert stored.filters == lot_filters()
    attempts = [p for p in rig.payloads() if p.get("phase") == "pre_send"]
    assert attempts[0]["filters_stale"] is False
    assert attempts[0]["filters_fetched_at_utc"] == rig.clock.now().isoformat()


# --------------------------------------------------------------------------- #
# Task 2: no filters, wrong filters, entries never stale, the plan snapshot as tier 2.
# --------------------------------------------------------------------------- #

PHASE_PRE_SEND = "pre_send"


async def test_no_live_read_and_nothing_stored_fails_closed_and_retries_next_step() -> None:
    rig = make_filter_rig(D("0.004"))
    rig.fake.fail_next("symbol_lot_filters", TimeoutError("exchangeInfo timed out"))

    closed = await close(rig)

    assert closed is False
    assert rig.fake.calls_to("place_market_close") == []
    assert rig.safe_mode.entered_reasons == ["EMERGENCY_CLOSE_FAILED"]
    assert [(a.event, a.reason) for a in rig.alerts.alerts] == [
        ("EMERGENCY_CLOSE_FAILED", "LOT_FILTERS_UNAVAILABLE")
    ]
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.status == "CLOSE_FAILED"
    assert rig.closer.last_result.reason == "LOT_FILTERS_UNAVAILABLE"
    assert all("filters_stale" not in p for p in rig.payloads())

    # The next step: the exchange answers again, the same plan closes (nothing was marked done).
    assert await close(rig) is True
    assert rig.sent_quantities() == [D("0.004")]


async def test_an_unreadable_store_is_no_stored_filters_not_a_crash() -> None:
    rig = make_filter_rig(D("0.004"))
    rig.source._store = FailingLotFilterStore()  # noqa: SLF001
    rig.fake.fail_next("symbol_lot_filters", TimeoutError("exchangeInfo timed out"))

    assert await close(rig) is False

    assert rig.fake.calls_to("place_market_close") == []
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.reason == "LOT_FILTERS_UNAVAILABLE"
    assert rig.source.last_store_error_type == "ConnectionError"


async def test_a_failing_store_write_never_blocks_a_good_live_read() -> None:
    rig = make_filter_rig(D("0.004"))
    rig.source._store = FailingLotFilterStore()  # noqa: SLF001

    assert await close(rig) is True

    assert rig.sent_quantities() == [D("0.004")]
    assert rig.source.last_store_error_type == "ConnectionError"


async def test_an_exposure_below_the_market_minimum_is_never_rounded_up() -> None:
    rig = make_filter_rig(D("0.0005"), stored=lot_filters(minimum="0.001"))
    rig.fake.fail_next("symbol_lot_filters", TimeoutError("exchangeInfo timed out"))

    closed = await close(rig)

    assert closed is False
    assert rig.fake.calls_to("place_market_close") == []
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.reason == "NO_VALID_PART"
    assert rig.fake.positions[SYMBOL] == D("0.0005")


async def test_a_split_close_on_stale_filters_stays_one_part_at_a_time() -> None:
    rig = make_filter_rig(D("0.005"), stored=lot_filters(market_max="0.002"))
    rig.fake.fail_next("symbol_lot_filters", TimeoutError("exchangeInfo timed out"))

    closed = await close(rig)

    assert closed is True
    assert rig.sent_quantities() == [D("0.002"), D("0.002"), D("0.001")]
    order = [c["method"] for c in rig.fake.calls if c["method"] != "query_order_by_client"]
    assert order == [
        "snapshot_positions",
        "symbol_lot_filters",
        "place_market_close",
        "snapshot_positions",
        "place_market_close",
        "snapshot_positions",
        "place_market_close",
        "snapshot_positions",
        "snapshot_positions",
    ]
    stale = {p["filters_stale"] for p in rig.payloads() if "filters_stale" in p}
    assert stale == {True}


async def test_a_filter_rejected_close_is_not_resent_with_the_same_payload() -> None:
    rig = make_filter_rig(D("0.0045"), stored=lot_filters())
    rig.fake.fail_next("symbol_lot_filters", TimeoutError("exchangeInfo timed out"))
    rig.fake.reject_next("place_market_close", -4005)  # QTY_GREATER_THAN_MAX_QTY: a filter code

    assert await close(rig) is False
    first_id = rig.fake.calls_to("place_market_close")[0]["kwargs"]["new_client_order_id"]
    assert rig.sent_quantities() == [D("0.004")]

    # Next step, live filters still unreadable: the stored filters give the SAME quantity, which
    # the exchange just refused for its filters. Nothing is sent.
    rig.fake.fail_next("symbol_lot_filters", TimeoutError("exchangeInfo timed out"))
    assert await close(rig) is False
    assert rig.sent_quantities() == [D("0.004")]
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.reason == "FILTER_REJECTED_SAME_PAYLOAD"

    # Next step, the exchange answers with the fresh filters: the quantity is recomputed and sent
    # under a NEW attempt number.
    rig.fake.set_lot_filters(SYMBOL, lot_filters(step="0.0005"))
    assert await close(rig) is True
    assert rig.sent_quantities() == [D("0.004"), D("0.0045")]
    second_id = rig.fake.calls_to("place_market_close")[1]["kwargs"]["new_client_order_id"]
    assert second_id != first_id
    assert second_id.endswith("0002")


async def test_an_ordinary_rejection_keeps_the_existing_behaviour() -> None:
    # -2022 (reduce-only on a smaller position) is not a filter code: no marker, same ids as ever.
    rig = make_filter_rig(D("0.004"))
    rig.fake.reject_next("place_market_close", -2022)

    assert await close(rig) is False
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.reason == "REJECTED_NOT_FLAT"
    assert await close(rig) is True
    assert rig.sent_quantities() == [D("0.004"), D("0.004")]


async def test_entry_path_never_uses_stored_filters() -> None:
    rig = make_filter_rig(D("0.004"), stored=lot_filters())
    rig.fake.fail_next("symbol_lot_filters", TimeoutError("exchangeInfo timed out"))

    with pytest.raises(LotFiltersUnavailable):
        await rig.source.for_entry(SYMBOL)

    # The stored row exists and the next live read works: for_entry returns the live filters.
    assert rig.store.get(SYMBOL) is not None
    assert await rig.source.for_entry(SYMBOL) == lot_filters()


async def test_entry_path_refuses_a_non_filter_answer() -> None:
    rig = make_filter_rig(D("0.004"), stored=lot_filters())
    rig.fake.set_lot_filters(SYMBOL, object())

    with pytest.raises(LotFiltersUnavailable) as caught:
        await rig.source.for_entry(SYMBOL)

    assert caught.value.error_type == "InvalidFilters"


async def test_a_pause_leaves_the_close_gated_even_with_stored_filters() -> None:
    rig = make_filter_rig(D("0.004"), stored=lot_filters())
    rig.fake.fail_next("symbol_lot_filters", PreSendRefusal("rest gate paused"))
    rig.fake.fail_next("place_market_close", PreSendRefusal("rest gate paused"))

    closed = await close(rig)

    # The stored filters sized a part, but the close itself is refused by the same gate: it is
    # NOT_SENT (nothing reached the exchange, the position is untouched), never a bypass.
    assert closed is False
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.status == "NOT_SENT"
    assert rig.fake.positions[SYMBOL] == D("0.004")


def _plan_snapshot(**overrides: Any) -> PlanConstraintSnapshot:
    observed = VirtualTime().now() - timedelta(minutes=30)
    fields: dict[str, Any] = {
        "trade_plan_id": "plan-snapshot-0001",
        "symbol": SYMBOL,
        "price_tick_size": D("0.01"),
        "quantity_step_size": D("0.001"),
        "min_quantity": D("0.001"),
        "max_quantity": D("1000"),
        "min_notional": D("100"),
        "market_lot_min_quantity": D("0.001"),
        "market_lot_max_quantity": D("120"),
        "market_lot_step_size": D("0.001"),
        "percent_price_multiplier_up": None,
        "percent_price_multiplier_down": None,
        "percent_price_multiplier_decimals": None,
        "working_type": "MARK_PRICE",
        "margin_type": None,
        "leverage": None,
        "equity_used": None,
        "constraints_observed_at_utc": observed,
        "captured_at_utc": observed,
    }
    fields.update(overrides)
    return PlanConstraintSnapshot(**fields)


async def test_the_plan_snapshot_is_tier_two_when_it_is_complete_for_the_close() -> None:
    snapshot = _plan_snapshot()
    asked: list[str] = []

    def snapshot_for(trade_plan_id: str) -> PlanConstraintSnapshot | None:
        asked.append(trade_plan_id)
        return snapshot

    rig = make_filter_rig(D("0.0045"), snapshot_for=snapshot_for)
    rig.fake.fail_next("symbol_lot_filters", TimeoutError("exchangeInfo timed out"))

    await close(rig)

    assert asked == [resting_entry_for_tests().trade_plan_id]
    assert rig.sent_quantities() == [D("0.004")]
    attempts = [p for p in rig.payloads() if p.get("phase") == PHASE_PRE_SEND]
    assert attempts[0]["filters_stale"] is True
    assert attempts[0]["filters_fetched_at_utc"] == snapshot.constraints_observed_at_utc.isoformat()


@pytest.mark.parametrize(
    "missing",
    ["max_quantity", "market_lot_min_quantity", "market_lot_max_quantity", "market_lot_step_size"],
)
async def test_an_incomplete_plan_snapshot_is_not_a_fallback(missing: str) -> None:
    rig = make_filter_rig(D("0.004"), snapshot_for=lambda _id: _plan_snapshot(**{missing: None}))
    rig.fake.fail_next("symbol_lot_filters", TimeoutError("exchangeInfo timed out"))

    assert await close(rig) is False

    assert rig.fake.calls_to("place_market_close") == []
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.reason == "LOT_FILTERS_UNAVAILABLE"


async def test_the_stored_row_outranks_the_plan_snapshot() -> None:
    rig = make_filter_rig(
        D("0.0045"),
        stored=lot_filters(step="0.0005"),
        snapshot_for=lambda _id: _plan_snapshot(),
    )
    rig.fake.fail_next("symbol_lot_filters", TimeoutError("exchangeInfo timed out"))

    await close(rig)

    assert rig.sent_quantities() == [D("0.0045")]  # the stored step 0.0005, not the snapshot's


async def test_a_snapshot_of_another_symbol_or_a_failing_callable_is_no_fallback() -> None:
    def broken(_id: str) -> PlanConstraintSnapshot | None:
        raise ConnectionError("store down")

    rig = make_filter_rig(D("0.004"), snapshot_for=broken)
    rig.fake.fail_next("symbol_lot_filters", TimeoutError("exchangeInfo timed out"))
    assert await close(rig) is False
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.reason == "LOT_FILTERS_UNAVAILABLE"

    other = make_filter_rig(D("0.004"), snapshot_for=lambda _id: _plan_snapshot(symbol="ETHUSDT"))
    other.fake.fail_next("symbol_lot_filters", TimeoutError("exchangeInfo timed out"))
    assert await close(other) is False
    assert other.closer.last_result is not None
    assert other.closer.last_result.reason == "LOT_FILTERS_UNAVAILABLE"


def test_for_emergency_close_is_called_only_from_the_emergency_closer() -> None:
    root = Path(__file__).resolve().parents[1]
    callers: set[str] = set()
    for path in sorted((root / "src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "for_emergency_close":
                callers.add(path.relative_to(root).as_posix())
    assert callers == {"src/execution/emergency_close.py"}
