"""The automatic reduce-only MARKET close (plan 19-12; D034, D-15, D-16, D-17).

Every scenario runs against the stateful Phase 19 fake exchange with fake lot filters and
virtual time. Nothing sleeps and nothing touches a network. A green test proves agreement with
the fake's labelled rules (tests/support/fake_binance_exchange.py), not with mainnet: the
-2022 answer to a reduce-only MARKET on a flat position is a TEST CONVENTION and UNPROVEN
(research A4/A8), and no Demo or mainnet value is asserted anywhere in this file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
from src.domain.lot_filters import LotFilters
from src.execution.emergency_close import (
    EmergencyCloseResult,
    MarketEmergencyCloser,
)
from src.execution.order_ids import derive_close_order_id
from src.execution.protection import EmergencyCloser

from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
from tests.support.protection_doubles import (
    TEST_ONLY_PLAN_HASH,
    TEST_ONLY_SYMBOL,
    RecordingAlerts,
    RecordingSafeMode,
    resting_entry_for_tests,
)
from tests.support.stream_sinks import RecordingJournal
from tests.support.virtual_time import VirtualTime

D = Decimal
PLAN_HASH = TEST_ONLY_PLAN_HASH
SYMBOL = TEST_ONLY_SYMBOL
ENTRY_PRICE = D("60000")

# Allowed characters of every derived id (a subset of the Binance client id charset).
ID_CHARSET = set("0123456789abcdef-x")


def lot_filters(
    *,
    market_max: str = "120",
    step: str = "0.001",
    minimum: str = "0.001",
    lot_max: str = "1000",
) -> LotFilters:
    """FAKE filters (TEST_ONLY numbers, not exchangeInfo)."""
    return LotFilters(
        symbol=SYMBOL,
        price_tick_size=D("0.01"),
        lot_min_quantity=D(minimum),
        lot_max_quantity=D(lot_max),
        lot_step_size=D(step),
        market_lot_min_quantity=D(minimum),
        market_lot_max_quantity=D(market_max),
        market_lot_step_size=D(step),
        min_notional=D("100"),
    )


class LoggingJournal(RecordingJournal):
    """A `RecordingJournal` that also appends each record to a shared ordering log."""

    def __init__(self, log: list[str]) -> None:
        super().__init__()
        self._log = log

    def record(self, event: Any) -> None:
        payload = json.loads(event.payload_json) if event.payload_json else {}
        self._log.append(f"journal:{payload.get('phase')}")
        super().record(event)


@dataclass
class CloseRig:
    fake: BinanceSemanticsFakeAdapter
    journal: LoggingJournal
    safe_mode: RecordingSafeMode
    alerts: RecordingAlerts
    clock: VirtualTime
    closer: MarketEmergencyCloser
    log: list[str]

    def phases(self) -> list[str]:
        return [json.loads(e.payload_json)["phase"] for e in self.journal.calls]

    def sent_ids(self) -> list[str]:
        return [
            c["kwargs"]["new_client_order_id"] for c in self.fake.calls_to("place_market_close")
        ]

    def sent_quantities(self) -> list[Decimal]:
        return [c["kwargs"]["quantity"] for c in self.fake.calls_to("place_market_close")]


def make_close_rig(
    position: Decimal | None,
    *,
    filters: LotFilters | None = None,
) -> CloseRig:
    """A closer over the fake exchange holding `position` (signed; None: no position)."""
    clock = VirtualTime()
    fake = BinanceSemanticsFakeAdapter(now_utc=clock.now(), enforce_flat_stop_rejection=True)
    if position is not None and position != 0:
        fake._apply_position_delta(SYMBOL, position, ENTRY_PRICE)
    fake.set_lot_filters(SYMBOL, filters if filters is not None else lot_filters())
    log: list[str] = []
    original = fake.place_market_close

    async def logged(**kwargs: Any) -> Any:
        log.append("adapter.place_market_close")
        return await original(**kwargs)

    fake.place_market_close = logged  # type: ignore[method-assign]
    journal = LoggingJournal(log)
    safe_mode = RecordingSafeMode()
    alerts = RecordingAlerts()
    closer = MarketEmergencyCloser(
        adapter=fake,
        journal=journal,
        safe_mode_controller=safe_mode,
        alert_sink=alerts,
        clock=clock,
    )
    return CloseRig(
        fake=fake,
        journal=journal,
        safe_mode=safe_mode,
        alerts=alerts,
        clock=clock,
        closer=closer,
        log=log,
    )


# --------------------------------------------------------------------------- #
# derive_close_order_id (Task 1).
# --------------------------------------------------------------------------- #


def test_close_order_id_shape_and_determinism() -> None:
    plan_hash = "0123456789abcdef" * 4
    first = derive_close_order_id(plan_hash=plan_hash, attempt_no=1)
    assert first == "xc-" + plan_hash[:29] + "0001"
    assert len(first) == 36
    assert set(first) <= ID_CHARSET
    assert derive_close_order_id(plan_hash=plan_hash, attempt_no=1) == first
    assert derive_close_order_id(plan_hash=plan_hash, attempt_no=12) == (
        "xc-" + plan_hash[:29] + "0012"
    )
    assert derive_close_order_id(plan_hash=plan_hash, attempt_no=9999).endswith("9999")


def test_close_order_id_never_collides_with_the_other_derived_ids() -> None:
    from src.execution.order_ids import derive_algo_client_id, derive_client_order_id

    plan_hash = PLAN_HASH
    others = {
        derive_client_order_id(plan_hash=plan_hash, role=role)
        for role in ("ENTRY", "STOP_LOSS", "TAKE_PROFIT_1", "TAKE_PROFIT_2")
    } | {
        derive_algo_client_id(plan_hash=plan_hash, role=role)
        for role in ("ENTRY", "STOP_LOSS", "TAKE_PROFIT_1", "TAKE_PROFIT_2")
    }
    closes = {derive_close_order_id(plan_hash=plan_hash, attempt_no=n) for n in (1, 2, 3)}
    assert len(closes) == 3
    assert closes.isdisjoint(others)


@pytest.mark.parametrize("attempt_no", [0, -1, 10000, True, False, 1.0, "1", None])
def test_close_order_id_refuses_a_bad_attempt_number(attempt_no: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        derive_close_order_id(plan_hash=PLAN_HASH, attempt_no=attempt_no)  # type: ignore[arg-type]


@pytest.mark.parametrize("plan_hash", ["", "abc", "A" * 64, "g" * 64, 5])
def test_close_order_id_refuses_a_bad_plan_hash(plan_hash: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        derive_close_order_id(plan_hash=plan_hash, attempt_no=1)  # type: ignore[arg-type]


def test_role_codes_are_untouched() -> None:
    from src.execution.order_ids import ROLE_CODES

    assert ROLE_CODES == {
        "ENTRY": "EN",
        "STOP_LOSS": "SL",
        "TAKE_PROFIT_1": "T1",
        "TAKE_PROFIT_2": "T2",
    }


# --------------------------------------------------------------------------- #
# Tracer: one part, REST re-check, FLAT (Task 1).
# --------------------------------------------------------------------------- #


async def test_tracer_one_part_closes_the_position_and_reports_flat() -> None:
    rig = make_close_rig(D("0.004"))
    entry = resting_entry_for_tests()

    closed = await rig.closer.close_position(entry=entry, reason="CLOSE_REQUIRED")

    assert closed is True
    sends = rig.fake.calls_to("place_market_close")
    assert len(sends) == 1
    assert sends[0]["kwargs"] == {
        "symbol": SYMBOL,
        "side": "SELL",
        "position_side": "BOTH",
        "quantity": D("0.004"),
        "new_client_order_id": derive_close_order_id(plan_hash=PLAN_HASH, attempt_no=1),
    }
    assert rig.fake.positions[SYMBOL] == 0
    result = rig.closer.last_result
    assert isinstance(result, EmergencyCloseResult)
    assert result.status == "FLAT"
    assert result.parts_sent == 1
    assert rig.safe_mode.entered_reasons == []
    assert rig.alerts.alerts == []


async def test_tracer_closes_a_short_position_with_a_buy() -> None:
    rig = make_close_rig(D("-0.004"))
    entry = resting_entry_for_tests(
        side="SHORT",
        entry_side="SELL",
        exit_side="BUY",
        sl_trigger_price=D("61000.00"),
        tp1_trigger_price=D("58000.00"),
        tp2_trigger_price=D("56000.00"),
    )

    assert await rig.closer.close_position(entry=entry, reason="CLOSE_REQUIRED") is True
    assert rig.fake.calls_to("place_market_close")[0]["kwargs"]["side"] == "BUY"


async def test_tracer_journals_pre_send_before_the_send_and_post_send_after() -> None:
    rig = make_close_rig(D("0.004"))

    await rig.closer.close_position(entry=resting_entry_for_tests(), reason="CLOSE_REQUIRED")

    assert rig.log == [
        "journal:pre_send",
        "adapter.place_market_close",
        "journal:post_send",
    ]
    events = rig.journal.calls
    assert {e.event_type for e in events} == {"EMERGENCY_CLOSE"}
    expected_id = derive_close_order_id(plan_hash=PLAN_HASH, attempt_no=1)
    for event in events:
        payload = json.loads(event.payload_json)
        # Scalar fields only: no nested object, no list.
        assert all(isinstance(v, (str, int, bool)) or v is None for v in payload.values())
        assert payload["symbol"] == SYMBOL
        assert payload["plan_hash"] == PLAN_HASH
        assert payload["client_order_id"] == expected_id
        assert payload["attempt_no"] == 1
        assert payload["reason"] == "CLOSE_REQUIRED"
        assert event.entity_id == expected_id


async def test_hedge_entry_is_refused_with_value_error_and_nothing_is_sent() -> None:
    rig = make_close_rig(D("0.004"))
    entry = resting_entry_for_tests(position_mode="HEDGE")

    with pytest.raises(ValueError, match="HEDGE"):
        await rig.closer.close_position(entry=entry, reason="CLOSE_REQUIRED")

    assert rig.fake.calls_to("place_market_close") == []
    assert rig.fake.positions[SYMBOL] == D("0.004")


def test_the_closer_implements_the_coordinator_protocol() -> None:
    assert EmergencyCloser in MarketEmergencyCloser.__mro__
