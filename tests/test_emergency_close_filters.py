"""The emergency close and the last validated lot filters (Phase 20, plan 20-18; Q3, D-21).

Every scenario runs against the stateful Phase 19 fake exchange with fake lot filters, an
in-memory filter store and virtual time. Nothing sleeps and nothing touches a network. A green
test proves agreement with the fake's labelled rules, not with Binance: whether Binance accepts
a close sized on stale filters is [NOT_TESTED] (best effort, Q3).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from src.domain.lot_filters import LotFilters
from src.execution.emergency_close import MarketEmergencyCloser
from src.execution.lot_filter_source import LotFilterSource

from tests.support.execution_limits import test_only_execution_limits as limits_with
from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
from tests.support.lot_filter_fakes import InMemoryLotFilterStore
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
    source = LotFilterSource(adapter=fake, store=store, limits=limits_with(), clock=clock)
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
