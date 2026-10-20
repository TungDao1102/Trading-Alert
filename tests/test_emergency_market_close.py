"""The automatic reduce-only MARKET close (plan 19-12; D034, D-15, D-16, D-17).

Every scenario runs against the stateful Phase 19 fake exchange with fake lot filters and
virtual time. Nothing sleeps and nothing touches a network. A green test proves agreement with
the fake's labelled rules (tests/support/fake_binance_exchange.py), not with mainnet: the
-2022 answer to a reduce-only MARKET on a flat position is a TEST CONVENTION and UNPROVEN
(research A4/A8), and no Demo or mainnet value is asserted anywhere in this file.
"""

from __future__ import annotations

import ast
import json
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from binance_sdk_derivatives_trading_usds_futures import BadRequestError
from src.adapters.binance_usdm import OrderProbe
from src.domain.exchange_errors import PreSendRefusal
from src.domain.lot_filters import LotFilters
from src.execution.emergency_close import (
    EmergencyCloseResult,
    MarketEmergencyCloser,
    discover_next_attempt_no,
)
from src.execution.order_ids import derive_close_order_id
from src.execution.protection import EmergencyCloser

from tests.support.ast_guards import (
    float_constructor_calls,
    forbidden_imports,
    wall_clock_calls,
)
from tests.support.execution_limits import test_only_execution_limits as limits_with
from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
from tests.support.protection_doubles import (
    TEST_ONLY_PLAN_HASH,
    TEST_ONLY_SYMBOL,
    RecordingAlerts,
    RecordingSafeMode,
    resting_entry_for_tests,
)
from tests.support.stream_sinks import RecordingJournal
from tests.support.virtual_time import TEST_ONLY_VIRTUAL_START, VirtualTime

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


_RIGS: list[CloseRig] = []


@pytest.fixture(autouse=True)
def no_attempt_id_is_ever_sent_twice() -> Iterator[None]:
    """Across every scenario of this file: no attempt id appears twice in the fake's calls."""
    _RIGS.clear()
    yield
    for rig in _RIGS:
        ids = rig.sent_ids()
        assert len(ids) == len(set(ids)), f"an attempt id was sent twice: {ids}"


def make_close_rig(
    position: Decimal | None,
    *,
    filters: LotFilters | None = None,
    limits: Any = None,
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
        limits=limits if limits is not None else limits_with(),
    )
    rig = CloseRig(
        fake=fake,
        journal=journal,
        safe_mode=safe_mode,
        alerts=alerts,
        clock=clock,
        closer=closer,
        log=log,
    )
    _RIGS.append(rig)
    return rig


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

    # post_send records the ACK only; "filled" is journaled when a query of the attempt id
    # proves it FILLED (19-REVIEW WR-03: an ACK is never a close).
    assert rig.log == [
        "journal:pre_send",
        "adapter.place_market_close",
        "journal:post_send",
        "journal:filled",
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


# --------------------------------------------------------------------------- #
# Parts above the market maximum, re-check after each part, impossible part (Task 2).
# --------------------------------------------------------------------------- #


def whole_unit_filters(*, market_max: str) -> LotFilters:
    """FAKE filters on a whole-unit grid so a small position needs several parts."""
    return lot_filters(market_max=market_max, step="1", minimum="1")


def method_order(rig: CloseRig) -> list[str]:
    return [c["method"] for c in rig.fake.calls if c["method"] != "query_order_by_client"]


def assert_failed_into_safe_mode(rig: CloseRig, *, code: str) -> None:
    assert rig.safe_mode.entered_reasons == ["EMERGENCY_CLOSE_FAILED"]
    assert [(a.event, a.plan_hash, a.symbol, a.reason) for a in rig.alerts.alerts] == [
        ("EMERGENCY_CLOSE_FAILED", PLAN_HASH, SYMBOL, code)
    ]
    assert "failed" in rig.phases()
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.status == "CLOSE_FAILED"
    assert rig.closer.last_result.reason == code


async def close(rig: CloseRig, reason: str = "CLOSE_REQUIRED") -> bool:
    return await rig.closer.close_position(entry=resting_entry_for_tests(), reason=reason)


async def test_a_position_above_the_market_maximum_closes_in_three_parts() -> None:
    rig = make_close_rig(D("12"), filters=whole_unit_filters(market_max="5"))

    closed = await close(rig)

    assert closed is True
    assert rig.sent_quantities() == [D("5"), D("5"), D("2")]
    assert rig.sent_ids() == [
        derive_close_order_id(plan_hash=PLAN_HASH, attempt_no=n) for n in (1, 2, 3)
    ]
    # A position read opens the call and follows every send; the flat read is confirmed by a
    # second, fresh read before the closer answers flat (T-8-30, 19-REVIEW CR-03).
    assert method_order(rig) == [
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
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.status == "FLAT"
    assert rig.closer.last_result.parts_sent == 3
    assert rig.safe_mode.entered_reasons == []


async def test_the_next_part_comes_from_the_rest_position_not_a_running_total() -> None:
    rig = make_close_rig(D("12"), filters=whole_unit_filters(market_max="5"))
    original = rig.fake.place_market_close
    calls = 0

    async def with_a_stop_firing(**kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        result = await original(**kwargs)
        if calls == 1:
            # The stop fired as well: the exchange now holds 12 - 5 - 3 = 4, not 7.
            rig.fake._apply_position_delta(SYMBOL, D("-3"), ENTRY_PRICE)
        return result

    rig.fake.place_market_close = with_a_stop_firing  # type: ignore[method-assign]

    closed = await close(rig)

    assert closed is True
    assert rig.sent_quantities() == [D("5"), D("4")]
    assert rig.fake.positions[SYMBOL] == 0


async def test_an_unrepresentable_remainder_sends_nothing_and_escalates() -> None:
    # 0.5 is below the whole-unit minimum: no valid part exists (nothing is rounded up).
    rig = make_close_rig(D("0.5"), filters=whole_unit_filters(market_max="5"))

    closed = await close(rig)

    assert closed is False
    assert rig.fake.calls_to("place_market_close") == []
    assert_failed_into_safe_mode(rig, code="NO_VALID_PART")
    assert rig.fake.positions[SYMBOL] == D("0.5")


async def test_a_failed_live_filter_read_is_the_no_valid_part_branch_without_fallback() -> None:
    rig = make_close_rig(D("0.004"))
    rig.fake.fail_next("symbol_lot_filters", RuntimeError("exchangeInfo unavailable"))

    closed = await close(rig)

    assert closed is False
    assert rig.fake.calls_to("place_market_close") == []
    assert_failed_into_safe_mode(rig, code="LOT_FILTERS_UNAVAILABLE")


async def test_an_unreadable_position_never_declares_safety() -> None:
    rig = make_close_rig(D("0.004"))
    rig.fake.fail_next("snapshot_positions", RuntimeError("position read failed"))

    closed = await close(rig)

    assert closed is False
    assert rig.fake.calls_to("place_market_close") == []
    assert_failed_into_safe_mode(rig, code="POSITION_READ_FAILED")


async def test_a_failed_re_read_after_a_part_stops_without_another_send() -> None:
    rig = make_close_rig(D("12"), filters=whole_unit_filters(market_max="5"))
    original = rig.fake.snapshot_positions
    reads = 0

    async def second_read_fails(**kwargs: Any) -> Any:
        nonlocal reads
        reads += 1
        if reads == 2:
            raise RuntimeError("position read failed")
        return await original(**kwargs)

    rig.fake.snapshot_positions = second_read_fails  # type: ignore[method-assign]

    closed = await close(rig)

    assert closed is False
    assert len(rig.fake.calls_to("place_market_close")) == 1
    assert_failed_into_safe_mode(rig, code="POSITION_READ_FAILED")


async def test_a_position_already_flat_sends_nothing_and_is_flat() -> None:
    rig = make_close_rig(None)

    closed = await close(rig)

    assert closed is True
    assert rig.fake.calls_to("place_market_close") == []
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.status == "FLAT"
    assert rig.closer.last_result.parts_sent == 0
    assert rig.safe_mode.entered_reasons == []
    assert rig.alerts.alerts == []


async def test_a_single_empty_first_read_is_not_flat_and_sends_nothing() -> None:
    """19-REVIEW CR-03 / T-8-30: the opening read is a transient empty answer, the next is real.

    The old closer answered True (FLAT) on that one read, and the coordinator then swept every
    protective leg of an open 0.004 position. Now the second, fresh read shows the position:
    nothing is sent in this call, the close fails closed and the coordinator retries.
    """
    from tests.support.protection_doubles import script_empty_position_reads

    rig = make_close_rig(D("0.004"))
    script_empty_position_reads(rig.fake, [True, False])

    closed = await close(rig)

    assert closed is False
    assert rig.fake.calls_to("place_market_close") == []
    assert rig.fake.positions[SYMBOL] == D("0.004")
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.status == "CLOSE_FAILED"
    assert_failed_into_safe_mode(rig, code="TRANSIENT_POSITION_GAP")
    assert "already_flat" not in rig.phases()


async def test_a_single_empty_read_after_a_part_is_not_flat_and_sends_no_more() -> None:
    """After the first of three parts the read is a transient empty answer; 7 is still open.

    The old closer answered True after that part (7 left open, then swept naked); now the
    confirming read shows 7, no further part is sent in this call and the close fails closed.
    """
    from tests.support.protection_doubles import script_empty_position_reads

    rig = make_close_rig(D("12"), filters=whole_unit_filters(market_max="5"))
    script_empty_position_reads(rig.fake, [False, True, False])

    closed = await close(rig)

    assert closed is False
    assert rig.sent_quantities() == [D("5")]
    assert rig.fake.positions[SYMBOL] == D("7")
    assert_failed_into_safe_mode(rig, code="TRANSIENT_POSITION_GAP")
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.parts_sent == 1


async def test_a_flat_answer_needs_two_consecutive_zero_reads() -> None:
    rig = make_close_rig(None)

    closed = await close(rig)

    assert closed is True
    assert method_order(rig) == ["snapshot_positions", "snapshot_positions"]


async def test_a_call_never_sends_more_parts_than_the_first_position_needs() -> None:
    from types import SimpleNamespace

    from src.adapters.binance_usdm import PositionSnapshot

    rig = make_close_rig(D("12"), filters=whole_unit_filters(market_max="5"))

    async def stuck_position(**kwargs: Any) -> Any:
        rig.fake._record_call("snapshot_positions", kwargs)
        return [
            PositionSnapshot(
                symbol=SYMBOL,
                position_side="BOTH",
                position_amt=D("12"),
                entry_price=ENTRY_PRICE,
                break_even_price=ENTRY_PRICE,
                mark_price=None,
                unrealized_profit=D("0"),
                liquidation_price=None,
                notional=None,
                margin_asset="USDT",
                update_time_utc=rig.clock.now(),
            )
        ]

    sent: set[str] = set()

    async def acknowledged_only(**kwargs: Any) -> Any:
        rig.fake._record_call("place_market_close", kwargs)
        sent.add(kwargs["new_client_order_id"])
        return SimpleNamespace(status="NEW")

    async def reported_filled(**kwargs: Any) -> Any:
        # Every sent attempt is reported FILLED by its id, yet the position never moves.
        rig.fake._record_call("query_order_by_client", kwargs)
        client_id = kwargs["orig_client_order_id"]
        if client_id in sent:
            return probe_found(client_id, "FILLED")
        return probe_absent(client_id)

    rig.fake.snapshot_positions = stuck_position  # type: ignore[method-assign]
    rig.fake.place_market_close = acknowledged_only  # type: ignore[method-assign]
    rig.fake.query_order_by_client = reported_filled  # type: ignore[method-assign]

    closed = await close(rig)

    # plan_close_parts(12) is three parts: the call stops after three confirmed parts, never
    # loops on. (19-REVIEW WR-03: each part counts only once a query proves it FILLED.)
    assert closed is False
    assert len(rig.fake.calls_to("place_market_close")) == 3
    assert rig.sent_ids() == [
        derive_close_order_id(plan_hash=PLAN_HASH, attempt_no=n) for n in (1, 2, 3)
    ]
    assert_failed_into_safe_mode(rig, code="PARTS_EXHAUSTED")
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.parts_sent == 3


async def test_every_failure_path_journals_a_failed_record_with_scalar_fields() -> None:
    rig = make_close_rig(D("0.5"), filters=whole_unit_filters(market_max="5"))

    await close(rig)

    failed = [e for e in rig.journal.calls if json.loads(e.payload_json)["phase"] == "failed"]
    assert len(failed) == 1
    payload = json.loads(failed[0].payload_json)
    assert payload["code"] == "NO_VALID_PART"
    assert payload["reason"] == "CLOSE_REQUIRED"
    assert all(isinstance(v, (str, int, bool)) or v is None for v in payload.values())


# --------------------------------------------------------------------------- #
# Ambiguity, query-before-resend, pre-send refusals, rejections, discovery (Task 3).
# --------------------------------------------------------------------------- #


def probe_absent(client_id: str) -> OrderProbe:
    return OrderProbe(
        client_order_id=client_id,
        found=False,
        order_id=None,
        status=None,
        update_time_utc=None,
    )


def probe_found(client_id: str, status: str | None) -> OrderProbe:
    return OrderProbe(
        client_order_id=client_id,
        found=True,
        order_id="ex-scripted",
        status=status,
        update_time_utc=TEST_ONLY_VIRTUAL_START,
    )


def script_probes(rig: CloseRig, answers: list[Any]) -> None:
    """Replace `query_order_by_client` by a script (an exception in the list is raised)."""
    queue = deque(answers)
    real = rig.fake.query_order_by_client

    async def scripted(**kwargs: Any) -> Any:
        if not queue:
            # Script exhausted: the fake's own answer (19-REVIEW WR-03 queries every sent
            # attempt by its id, so a later attempt is confirmed by the real fake).
            return await real(**kwargs)
        rig.fake._bind_real("query_order_by_client", kwargs)
        rig.fake._record_call("query_order_by_client", kwargs)
        answer = queue.popleft()
        if isinstance(answer, BaseException):
            raise answer
        return answer

    rig.fake.query_order_by_client = scripted  # type: ignore[method-assign]


def lose_the_answer(rig: CloseRig, *, result: Any = ...) -> None:
    """The next close reaches the exchange but its answer is lost: it raises TimeoutError, or
    (with `result=None`) returns None."""
    original = rig.fake.place_market_close
    pending = True

    async def lost(**kwargs: Any) -> Any:
        nonlocal pending
        answer = await original(**kwargs)
        if pending:
            pending = False
            if result is None:
                return None
            raise TimeoutError("answer lost")
        return answer

    rig.fake.place_market_close = lost  # type: ignore[method-assign]


def probed_ids(rig: CloseRig) -> list[str]:
    return [c["kwargs"]["orig_client_order_id"] for c in rig.fake.calls_to("query_order_by_client")]


ID_1 = derive_close_order_id(plan_hash=PLAN_HASH, attempt_no=1)
ID_2 = derive_close_order_id(plan_hash=PLAN_HASH, attempt_no=2)


@pytest.mark.parametrize("answer", ["raise", "none"])
async def test_an_ambiguous_send_that_reached_the_exchange_is_found_by_id_and_not_resent(
    answer: str,
) -> None:
    rig = make_close_rig(D("0.004"))
    lose_the_answer(rig, result=None if answer == "none" else ...)

    closed = await close(rig)

    assert closed is True
    assert rig.sent_ids() == [ID_1]
    # The first probe is the attempt discovery, the second the query before any resend.
    assert probed_ids(rig) == [ID_1, ID_1]
    assert "ambiguous" in rig.phases()
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.status == "FLAT"
    assert rig.safe_mode.entered_reasons == []


@pytest.mark.parametrize("status", ["EXPIRED", "CANCELED"])
async def test_an_attempt_found_terminal_without_closing_gets_a_fresh_id_for_the_next_part(
    status: str,
) -> None:
    rig = make_close_rig(D("0.004"))
    rig.fake.fail_next("place_market_close", TimeoutError("answer lost"))
    script_probes(rig, [probe_absent(ID_1), probe_found(ID_1, status)])

    closed = await close(rig)

    assert closed is True
    # The first send never reached the fake; the found-but-not-closing attempt consumed id 1.
    assert rig.sent_ids() == [ID_1, ID_2]
    assert rig.fake.positions[SYMBOL] == 0


@pytest.mark.parametrize("status", ["NEW", "PARTIALLY_FILLED"])
async def test_a_found_active_attempt_after_an_ambiguous_send_is_pending_without_a_resend(
    status: str,
) -> None:
    """19-REVIEW WR-03: a found, still-active attempt is PENDING until the poll deadline.

    Before WR-03 this ended PENDING_UNKNOWN with SAFE_MODE and an alert at once; now the attempt
    is known to exist, so it is polled by its id (nothing sent) and the alert waits for the
    owner's poll deadline (tested below).
    """
    rig = make_close_rig(D("0.004"))
    rig.fake.fail_next("place_market_close", TimeoutError("answer lost"))
    script_probes(rig, [probe_absent(ID_1), probe_found(ID_1, status)])

    closed = await close(rig)

    assert closed is False
    assert rig.sent_ids() == [ID_1]
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.status == "PENDING"
    assert rig.safe_mode.entered_reasons == []
    assert rig.alerts.alerts == []


@pytest.mark.parametrize("status", ["SOMETHING_ELSE", None])
async def test_a_found_attempt_with_an_unreadable_status_stops_without_a_resend(
    status: str | None,
) -> None:
    rig = make_close_rig(D("0.004"))
    rig.fake.fail_next("place_market_close", TimeoutError("answer lost"))
    script_probes(rig, [probe_absent(ID_1), probe_found(ID_1, status)])

    closed = await close(rig)

    assert closed is False
    assert rig.sent_ids() == [ID_1]
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.status == "PENDING_UNKNOWN"
    assert rig.safe_mode.entered_reasons == ["EMERGENCY_CLOSE_FAILED"]
    assert [a.event for a in rig.alerts.alerts] == ["EMERGENCY_CLOSE_FAILED"]


async def test_a_probe_that_raises_stops_into_safe_mode_without_a_resend() -> None:
    rig = make_close_rig(D("0.004"))
    rig.fake.fail_next("place_market_close", TimeoutError("answer lost"))
    script_probes(rig, [probe_absent(ID_1), RuntimeError("probe failed")])

    closed = await close(rig)

    assert closed is False
    assert rig.sent_ids() == [ID_1]
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.status == "PENDING_UNKNOWN"
    assert rig.safe_mode.entered_reasons == ["EMERGENCY_CLOSE_FAILED"]
    assert [a.event for a in rig.alerts.alerts] == ["EMERGENCY_CLOSE_FAILED"]


async def test_a_probe_answer_that_is_not_a_plain_bool_is_indeterminate() -> None:
    rig = make_close_rig(D("0.004"))
    rig.fake.fail_next("place_market_close", TimeoutError("answer lost"))
    indeterminate = OrderProbe(
        client_order_id=ID_1,
        found=None,  # type: ignore[arg-type]
        order_id=None,
        status=None,
        update_time_utc=None,
    )
    script_probes(rig, [probe_absent(ID_1), indeterminate])

    closed = await close(rig)

    assert closed is False
    assert rig.sent_ids() == [ID_1]
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.status == "PENDING_UNKNOWN"


async def test_wr03_absence_right_after_an_ambiguous_send_is_unknown_and_never_resent() -> None:
    """19-REVIEW WR-03 (Q5 applied to the close): found=False after an ambiguous send is UNKNOWN.

    The old closer read this as "proven absent" and sent attempt 0002 at once (and again on
    every later call). Now no new attempt is created, ever: the attempt is held UNKNOWN, with
    SAFE_MODE and exactly one critical alert, and every later call only queries 0001 again.
    """
    rig = make_close_rig(D("0.004"))
    rig.fake.fail_next("place_market_close", TimeoutError("answer lost"))

    closed = await close(rig)

    assert closed is False
    assert rig.sent_ids() == [ID_1]
    assert probed_ids(rig) == [ID_1, ID_1]
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.status == "PENDING_UNKNOWN"
    assert rig.closer.last_result.reason == "ABSENT_AFTER_AMBIGUOUS_SEND"
    assert rig.safe_mode.entered_reasons == ["EMERGENCY_CLOSE_FAILED"]
    assert [(a.event, a.reason) for a in rig.alerts.alerts] == [
        ("EMERGENCY_CLOSE_FAILED", "ABSENT_AFTER_AMBIGUOUS_SEND")
    ]

    for _ in range(5):
        assert await close(rig) is False

    assert rig.sent_ids() == [ID_1]
    # Every later call queries the same attempt id and nothing else (no discovery, no 0002).
    assert probed_ids(rig) == [ID_1] * 7
    assert rig.closer.last_result.status == "PENDING_UNKNOWN"
    assert len(rig.alerts.alerts) == 1
    assert rig.safe_mode.in_safe_mode is True
    assert rig.fake.positions[SYMBOL] == D("0.004")


async def test_a_pre_send_refusal_is_journaled_as_not_sent_and_nothing_is_resent() -> None:
    rig = make_close_rig(D("0.004"))
    rig.fake.fail_next("place_market_close", PreSendRefusal("rest gate paused"))

    closed = await close(rig)

    assert closed is False
    assert rig.sent_ids() == [ID_1]
    # No probe after the refusal (only the attempt discovery before the send), no resend.
    assert probed_ids(rig) == [ID_1]
    assert "not_sent" in rig.phases()
    assert [(a.event, a.reason) for a in rig.alerts.alerts] == [
        ("EMERGENCY_CLOSE_NOT_SENT", "PRE_SEND_REFUSED")
    ]
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.status == "NOT_SENT"
    assert rig.closer.last_result.parts_sent == 0
    # The coordinator's deadline keeps running; the closer makes no claim of safety.
    assert rig.fake.positions[SYMBOL] == D("0.004")


@pytest.mark.parametrize("code", [-2022, -2024])
async def test_a_reduce_only_rejection_on_a_position_that_is_already_flat_is_flat(
    code: int,
) -> None:
    rig = make_close_rig(D("0.004"))

    async def stop_fired_then_rejected(**kwargs: Any) -> Any:
        # The stop fired between the read and the send: the exchange is flat, the close is
        # rejected. The REJECTION CODE is a test convention (research A4/A8), not evidence.
        rig.fake._record_call("place_market_close", kwargs)
        rig.fake._apply_position_delta(SYMBOL, D("-0.004"), ENTRY_PRICE)
        raise BadRequestError(error_message="rejected", status_code=code)

    rig.fake.place_market_close = stop_fired_then_rejected  # type: ignore[method-assign]

    closed = await close(rig)

    assert closed is True
    assert rig.sent_ids() == [ID_1]
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.status == "FLAT"
    assert rig.safe_mode.entered_reasons == []


@pytest.mark.parametrize("code", [-2022, -2024])
async def test_a_reduce_only_rejection_on_an_open_position_fails_without_a_resend(
    code: int,
) -> None:
    rig = make_close_rig(D("0.004"))
    rig.fake.reject_next("place_market_close", code, "rejected")

    closed = await close(rig)

    assert closed is False
    assert rig.sent_ids() == [ID_1]
    assert_failed_into_safe_mode(rig, code="REJECTED_NOT_FLAT")
    # Rejected means nothing was placed: no probe followed the rejection.
    assert probed_ids(rig) == [ID_1]
    assert rig.fake.positions[SYMBOL] == D("0.004")


async def test_minus_2022_and_minus_2024_end_identically() -> None:
    outcomes = []
    for code in (-2022, -2024):
        rig = make_close_rig(D("0.004"))
        rig.fake.reject_next("place_market_close", code, "rejected")
        closed = await close(rig)
        outcomes.append(
            (
                closed,
                rig.closer.last_result,
                rig.sent_ids(),
                rig.safe_mode.entered_reasons,
                [(a.event, a.reason) for a in rig.alerts.alerts],
                rig.phases(),
            )
        )
    assert outcomes[0] == outcomes[1]


async def test_discover_next_attempt_no_returns_the_first_absent_number() -> None:
    rig = make_close_rig(D("12"), filters=whole_unit_filters(market_max="5"))
    assert await discover_next_attempt_no(adapter=rig.fake, symbol=SYMBOL, plan_hash=PLAN_HASH) == 1

    assert await close(rig) is True  # three parts: attempts 1, 2, 3

    assert await discover_next_attempt_no(adapter=rig.fake, symbol=SYMBOL, plan_hash=PLAN_HASH) == 4


async def test_a_second_call_after_a_crash_never_reuses_an_attempt_id() -> None:
    rig = make_close_rig(D("12"), filters=whole_unit_filters(market_max="5"))
    assert await close(rig) is True
    # "Restart": a new closer instance and a new position of the same plan on the exchange.
    rig.fake._apply_position_delta(SYMBOL, D("0.004"), ENTRY_PRICE)
    rig.fake.set_lot_filters(SYMBOL, lot_filters())
    fresh = MarketEmergencyCloser(
        adapter=rig.fake,
        journal=rig.journal,
        safe_mode_controller=rig.safe_mode,
        alert_sink=rig.alerts,
        clock=rig.clock,
        limits=limits_with(),
    )

    assert await fresh.close_position(entry=resting_entry_for_tests(), reason="CLOSE_REQUIRED")

    assert rig.sent_ids() == [
        derive_close_order_id(plan_hash=PLAN_HASH, attempt_no=n) for n in (1, 2, 3, 4)
    ]


async def test_discover_next_attempt_no_raises_when_a_probe_fails() -> None:
    rig = make_close_rig(D("0.004"))
    script_probes(rig, [RuntimeError("probe failed")])
    with pytest.raises(RuntimeError):
        await discover_next_attempt_no(adapter=rig.fake, symbol=SYMBOL, plan_hash=PLAN_HASH)


async def test_discover_next_attempt_no_raises_on_an_indeterminate_probe() -> None:
    rig = make_close_rig(D("0.004"))
    indeterminate = OrderProbe(
        client_order_id=ID_1,
        found=None,  # type: ignore[arg-type]
        order_id=None,
        status=None,
        update_time_utc=None,
    )
    script_probes(rig, [indeterminate])
    with pytest.raises(ValueError):
        await discover_next_attempt_no(adapter=rig.fake, symbol=SYMBOL, plan_hash=PLAN_HASH)


async def test_a_failing_attempt_discovery_sends_nothing_and_stops_into_safe_mode() -> None:
    rig = make_close_rig(D("0.004"))
    script_probes(rig, [RuntimeError("probe failed")])

    closed = await close(rig)

    assert closed is False
    assert rig.fake.calls_to("place_market_close") == []
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.status == "PENDING_UNKNOWN"
    assert rig.safe_mode.entered_reasons == ["EMERGENCY_CLOSE_FAILED"]
    assert [a.event for a in rig.alerts.alerts] == ["EMERGENCY_CLOSE_FAILED"]


# --------------------------------------------------------------------------- #
# 19-REVIEW WR-03 (owner decision): Q5 applied to the close. An ACK is PENDING, never CLOSED;
# nothing else is sent while the current attempt is not proven terminal; the poll deadline is
# the owner key protection.emergency_close_poll_timeout_ms (FAKE value 6161 in tests).
# --------------------------------------------------------------------------- #

POLL_TIMEOUT_MS = 6161  # TEST_ONLY value of tests/support/execution_limits.py


def advance_ms(rig: CloseRig, milliseconds: int) -> None:
    """Move the injected clock by whole milliseconds (exact, no float)."""
    from datetime import timedelta

    rig.clock._now += timedelta(milliseconds=milliseconds)


def resting_close_rig(position: Decimal, **kwargs: Any) -> CloseRig:
    """A rig whose MARKET closes are acknowledged NEW and rest until the test fills them."""
    rig = make_close_rig(position, **kwargs)
    rig.fake.market_close_rests = True
    return rig


def fill_close(rig: CloseRig, client_id: str) -> None:
    """The exchange executes the resting close `client_id` in full."""
    rig.fake.fill(client_id, price=ENTRY_PRICE)


async def test_wr03_an_ack_new_with_nothing_executed_is_pending_and_nothing_else_is_sent() -> None:
    rig = resting_close_rig(D("0.004"))

    closed = await close(rig)

    assert closed is False
    assert rig.sent_ids() == [ID_1]
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.status == "PENDING"
    assert rig.closer.last_result.reason == "ATTEMPT_NOT_TERMINAL"
    assert rig.closer.last_result.parts_sent == 0
    # Pending is not a failure: no SAFE_MODE and no alert from the closer before the deadline.
    assert rig.safe_mode.entered_reasons == []
    assert rig.alerts.alerts == []
    assert "post_send" in rig.phases()
    assert "filled" not in rig.phases()

    # Later calls (the coordinator's next steps) only query the same id: no second order.
    for _ in range(5):
        advance_ms(rig, 1000)
        assert await close(rig) is False
        assert rig.closer.last_result.status == "PENDING"

    assert rig.sent_ids() == [ID_1]
    assert probed_ids(rig) == [ID_1] * 7  # discovery, the poll after the ACK, five polls
    assert rig.fake.positions[SYMBOL] == D("0.004")
    assert rig.alerts.alerts == []


async def test_wr03_polled_to_filled_then_two_flat_reads_is_closed() -> None:
    rig = resting_close_rig(D("0.004"))
    assert await close(rig) is False
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.status == "PENDING"

    fill_close(rig, ID_1)
    closed = await close(rig)

    assert closed is True
    assert rig.sent_ids() == [ID_1]
    assert rig.closer.last_result.status == "FLAT"
    assert rig.closer.last_result.parts_sent == 1
    assert rig.phases().count("filled") == 1
    assert rig.safe_mode.entered_reasons == []
    assert rig.alerts.alerts == []
    # The poll of 0001, then the two consecutive zero reads of CR-03; no discovery, no send.
    assert [c["method"] for c in rig.fake.calls][-3:] == [
        "query_order_by_client",
        "snapshot_positions",
        "snapshot_positions",
    ]


async def test_wr03_polled_to_filled_with_exposure_left_sends_a_new_id_sized_from_rest() -> None:
    rig = resting_close_rig(D("0.004"))
    assert await close(rig) is False

    # While 0001 rests, a late entry fill adds 0.003; then 0001 executes its 0.004.
    rig.fake._apply_position_delta(SYMBOL, D("0.003"), ENTRY_PRICE)
    fill_close(rig, ID_1)
    rig.fake.market_close_rests = False  # the next close executes at once

    closed = await close(rig)

    assert closed is True
    assert rig.sent_ids() == [ID_1, ID_2]
    # The next part comes from the REST position read after 0001 was proven FILLED.
    assert rig.sent_quantities() == [D("0.004"), D("0.003")]
    assert rig.fake.positions[SYMBOL] == 0
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.status == "FLAT"
    assert rig.closer.last_result.parts_sent == 2
    assert rig.safe_mode.entered_reasons == []
    assert rig.alerts.alerts == []


async def test_wr03_an_attempt_ended_unfilled_while_pending_gets_a_new_id() -> None:
    rig = resting_close_rig(D("0.004"))
    assert await close(rig) is False

    rig.fake.cancel(ID_1)  # e.g. EXPIRED/CANCELED by the exchange without executing
    rig.fake.market_close_rests = False

    assert await close(rig) is True
    assert rig.sent_ids() == [ID_1, ID_2]
    assert "ended_unfilled" in rig.phases()


async def test_wr03_discovery_stops_on_a_found_attempt_that_is_not_terminal() -> None:
    from src.execution.emergency_close import CloseAttemptNotTerminal

    rig = resting_close_rig(D("0.004"))
    assert await close(rig) is False  # 0001 rests on the exchange as NEW

    with pytest.raises(CloseAttemptNotTerminal) as excinfo:
        await discover_next_attempt_no(adapter=rig.fake, symbol=SYMBOL, plan_hash=PLAN_HASH)
    assert excinfo.value.attempt_no == 1
    assert excinfo.value.client_order_id == ID_1

    # "Restart": a new closer with no memory sees 0001 in the history, adopts it and sends
    # nothing (the history is unknown while 0001 may still execute).
    fresh = MarketEmergencyCloser(
        adapter=rig.fake,
        journal=rig.journal,
        safe_mode_controller=rig.safe_mode,
        alert_sink=rig.alerts,
        clock=rig.clock,
        limits=limits_with(),
    )
    entry = resting_entry_for_tests()
    assert await fresh.close_position(entry=entry, reason="CLOSE_REQUIRED") is False
    assert rig.sent_ids() == [ID_1]
    assert fresh.last_result is not None
    assert fresh.last_result.status == "PENDING_UNKNOWN"
    assert fresh.last_result.reason == "ATTEMPT_HISTORY_NOT_TERMINAL"
    assert [(a.event, a.reason) for a in rig.alerts.alerts] == [
        ("EMERGENCY_CLOSE_FAILED", "ATTEMPT_HISTORY_NOT_TERMINAL")
    ]
    assert await fresh.close_position(entry=entry, reason="CLOSE_REQUIRED") is False
    assert rig.sent_ids() == [ID_1]
    assert len(rig.alerts.alerts) == 1  # one alert per episode

    # Once 0001 is terminal the adopted attempt resolves and the close ends flat.
    fill_close(rig, ID_1)
    assert await fresh.close_position(entry=entry, reason="CLOSE_REQUIRED") is True
    assert rig.sent_ids() == [ID_1]


async def test_wr03_the_poll_deadline_holds_unknown_with_one_alert_and_no_second_send() -> None:
    rig = resting_close_rig(D("0.004"))
    assert await close(rig) is False

    advance_ms(rig, POLL_TIMEOUT_MS - 1)
    assert await close(rig) is False
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.status == "PENDING"
    assert rig.alerts.alerts == []
    assert rig.safe_mode.entered_reasons == []

    advance_ms(rig, 1)  # exactly the deadline: reaching it escalates
    assert await close(rig) is False
    assert rig.closer.last_result.status == "PENDING_UNKNOWN"
    assert rig.closer.last_result.reason == "CLOSE_POLL_DEADLINE_PASSED"
    assert rig.safe_mode.entered_reasons == ["EMERGENCY_CLOSE_FAILED"]
    assert [(a.event, a.reason) for a in rig.alerts.alerts] == [
        ("EMERGENCY_CLOSE_FAILED", "CLOSE_POLL_DEADLINE_PASSED")
    ]

    # Long past the deadline: still UNKNOWN, SAFE_MODE kept, still exactly one alert, and never
    # an overlapping close to shorten the wait; the attempt keeps being reconciled by its id.
    for _ in range(10):
        advance_ms(rig, 60_000)
        assert await close(rig) is False
        assert rig.closer.last_result.status == "PENDING_UNKNOWN"
    assert rig.sent_ids() == [ID_1]
    assert len(rig.alerts.alerts) == 1
    assert rig.safe_mode.in_safe_mode is True
    assert len([p for p in rig.phases() if p == "failed"]) == 1
    assert set(probed_ids(rig)) == {ID_1}

    # The exchange finally executes 0001: the episode ends flat, nothing else was sent.
    fill_close(rig, ID_1)
    assert await close(rig) is True
    assert rig.sent_ids() == [ID_1]
    assert len(rig.alerts.alerts) == 1


@pytest.mark.parametrize(
    ("poll_timeout_ms", "max_unprotected_ms", "unknown_at_ms"),
    [(50_000, 1, 50_000), (1_000, 10**9, 1_000)],
)
async def test_wr03_the_deadline_is_the_new_limit_never_max_unprotected_ms(
    poll_timeout_ms: int, max_unprotected_ms: int, unknown_at_ms: int
) -> None:
    limits = limits_with(
        emergency_close_poll_timeout_ms=poll_timeout_ms, max_unprotected_ms=max_unprotected_ms
    )
    rig = resting_close_rig(D("0.004"), limits=limits)
    assert await close(rig) is False

    advance_ms(rig, unknown_at_ms - 1)
    assert await close(rig) is False
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.status == "PENDING"
    advance_ms(rig, 1)
    assert await close(rig) is False
    assert rig.closer.last_result.status == "PENDING_UNKNOWN"
    assert rig.sent_ids() == [ID_1]


def test_wr03_the_closer_never_reads_max_unprotected_ms() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {
        n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
    }
    assert "max_unprotected_ms" not in names
    assert "emergency_close_poll_timeout_ms" in names


def test_wr03_the_closer_refuses_while_its_poll_deadline_is_not_configured() -> None:
    from src.execution.execution_limits import ExecutionLimitsNotConfigured

    with pytest.raises(ExecutionLimitsNotConfigured) as excinfo:
        MarketEmergencyCloser(
            adapter=None,  # type: ignore[arg-type]
            journal=None,
            safe_mode_controller=None,
            alert_sink=None,  # type: ignore[arg-type]
            clock=None,  # type: ignore[arg-type]
            limits=limits_with(emergency_close_poll_timeout_ms=None),
        )
    assert "emergency_close_poll_timeout_ms" in str(excinfo.value)


async def test_wr03_found_false_after_an_ack_is_unknown_and_never_resent() -> None:
    rig = resting_close_rig(D("0.004"))
    assert await close(rig) is False
    # The exchange stops showing the acknowledged attempt (contradicts the ACK).
    rig.fake.open_orders.pop(ID_1)

    assert await close(rig) is False
    assert rig.closer.last_result is not None
    assert rig.closer.last_result.status == "PENDING_UNKNOWN"
    assert rig.closer.last_result.reason == "ATTEMPT_NOT_FOUND_AFTER_ACK"
    assert rig.sent_ids() == [ID_1]
    assert len(rig.alerts.alerts) == 1


async def test_wr03_coordinator_keeps_a_resting_close_blocking_and_never_sends_a_second() -> None:
    from src.execution.protection import ProtectionState

    from tests.support.protection_doubles import make_rig

    rig = await make_rig(real_closer=True)
    rig.fake.market_close_rests = True
    rig.fake.reject_next_algo(-2021)  # B5: the stop is rejected after the fill
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))

    await rig.coordinator.step()  # CLOSE_REQUIRED, the close is ACKed NEW and rests
    protection = rig.coordinator.protection_of(PLAN_HASH)
    assert protection is not None
    assert protection.state is ProtectionState.CLOSE_FAILED
    assert rig.coordinator.blocks_new_entries() is True
    close_id = rig.fake.calls_to("place_market_close")[0]["kwargs"]["new_client_order_id"]

    for _ in range(4):
        await rig.coordinator.step()
    assert len(rig.fake.calls_to("place_market_close")) == 1
    assert rig.coordinator.blocks_new_entries() is True
    assert rig.fake.positions[SYMBOL] == D("0.004")

    rig.fake.fill(close_id, price=ENTRY_PRICE)
    await rig.coordinator.step()
    protection = rig.coordinator.protection_of(PLAN_HASH)
    assert protection is not None
    assert protection.state is ProtectionState.FLAT
    assert len(rig.fake.calls_to("place_market_close")) == 1
    assert rig.fake.positions[SYMBOL] == 0


# --------------------------------------------------------------------------- #
# Purity and the no-message-text rule (D-21).
# --------------------------------------------------------------------------- #

SOURCE = Path(__file__).resolve().parent.parent / "src" / "execution" / "emergency_close.py"


def test_the_module_is_pure_orchestration() -> None:
    forbidden = forbidden_imports(
        SOURCE,
        [
            "binance*",
            "src.adapters",
            "polars",
            "pandas",
            "numpy",
            "scipy",
            "pydantic",
            "sqlalchemy",
            "psycopg",
            "telegram",
            "fastapi",
            "httpx",
            "requests",
            "asyncio",
            "time",
            "random",
        ],
    )
    assert forbidden == []
    assert float_constructor_calls(SOURCE) == []
    assert wall_clock_calls(SOURCE) == []
    names = {
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        for node in ast.walk(ast.parse(SOURCE.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
    }
    assert "sleep" not in names


def test_the_module_never_reads_exception_message_text() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    offenders: list[int] = []
    for handler in (n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler) and n.name):
        name = handler.name
        for node in ast.walk(handler):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == name
                and node.attr in {"args", "message", "error_message", "status_code", "__str__"}
            ):
                offenders.append(node.lineno)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"str", "repr", "format", "print"}
                and any(isinstance(a, ast.Name) and a.id == name for a in node.args)
            ):
                offenders.append(node.lineno)
            if (
                isinstance(node, ast.FormattedValue)
                and isinstance(node.value, ast.Name)
                and node.value.id == name
            ):
                offenders.append(node.lineno)
    assert offenders == []
