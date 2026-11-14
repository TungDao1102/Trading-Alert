"""Scheduled cancel of an unfilled entry past its plan expiry (plan 24-21; D-13, T-24-61, T-24-62).

The task body `cancel_expired_entries_once` runs on the live rig (real wiring, real coordinator,
the Binance-semantics fake exchange, virtual time). It reads the coordinator's plans in
AWAITING_FILL, the stored expiry through the plan store port, and a FRESH REST read of the entry;
only a resting entry with zero executed quantity past its expiry is cancelled, through
`expire_pending_entry`. A partial fill, a missing or unreadable order and a failed read are left
to the coordinator and journaled by class name. Protective legs are never touched.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.domain.enums import OrderRole
from src.domain.journal import JournalEvent
from src.execution.cancel_verification import CancelVerdict
from src.execution.order_ids import derive_client_order_id
from src.execution.protection import ProtectionState
from src.live.scheduled_cancel import (
    EVENT_SCHEDULED_CANCEL,
    OUTCOME_CANCEL_FAILED,
    OUTCOME_CANCELED,
    OUTCOME_EXPIRY_UNKNOWN,
    OUTCOME_LEFT_TO_COORDINATOR,
    OUTCOME_NOT_RESTING,
    OUTCOME_READ_FAILED,
    OUTCOME_REFUSED,
    REASON_UNRESTORED_CANCEL_FAILED,
    REASON_UNRESTORED_CANCEL_REFUSED,
    REASON_UNRESTORED_CANCEL_UNVERIFIED,
    REASON_UNRESTORED_PLAN_POSITION,
    REASON_UNRESTORED_POSITION_UNKNOWN,
    cancel_expired_entries_once,
    cancel_unrestored_entries,
)
from src.ops.alerts import ALERT_EVENTS, AlertSeverity
from src.reconcile.startup import UnrestorableEntry

from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
from tests.support.live_rig import LiveRig, forbid_real_sleep, make_live_rig
from tests.support.protection_doubles import RecordingAlerts
from tests.support.reconcile_doubles import RecordingJournal

D = Decimal
SOURCE = Path(__file__).resolve().parents[1] / "src" / "live" / "scheduled_cancel.py"


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


class StoredExpiry:
    """The plan store port over the rig's in-memory plans, keyed by plan hash."""

    def __init__(self, rig: LiveRig, *, error: BaseException | None = None) -> None:
        self._rig = rig
        self._error = error
        self.unknown: set[str] = set()
        self.reads = 0

    async def expiry_utc_for(self, plan_hash: str) -> datetime | None:
        self.reads += 1
        if self._error is not None:
            raise self._error
        if plan_hash in self.unknown:
            return None
        for plan in self._rig.stores.plans.values():
            if plan.plan_hash == plan_hash:
                return plan.expiry_utc
        return None


async def placed_rig() -> LiveRig:
    """The rig with one resting entry (AWAITING_FILL) and nothing filled."""
    rig = await make_live_rig()
    await rig.approve_and_confirm()
    await rig.wiring.service.drain()
    protection = rig.wiring.coordinator.protection_of(rig.plan.plan_hash)
    assert protection is not None and protection.state is ProtectionState.AWAITING_FILL
    return rig


async def run_once(rig: LiveRig, store: StoredExpiry, *, now: datetime | None = None) -> Any:
    when = rig.clock.now() if now is None else now
    return await cancel_expired_entries_once(
        coordinator=rig.wiring.coordinator,
        plan_store=store,
        adapter=rig.fake,  # type: ignore[arg-type]
        journal=rig.journal,
        spill=None,
        now_utc=when,
    )


async def move_past_expiry(rig: LiveRig, extra: float = 1.0) -> None:
    seconds = (rig.plan.expiry_utc - rig.clock.now()).total_seconds() + extra
    await rig.clock.advance(seconds)
    rig.fake.now_utc = rig.clock.now()


def scheduled_rows(rig: LiveRig) -> list[JournalEvent]:
    return rig.journal.by_type(EVENT_SCHEDULED_CANCEL)


# --------------------------------------------------------------------------- #
# The tracer: past expiry with zero fills, the entry is cancelled once.
# --------------------------------------------------------------------------- #


async def test_an_unfilled_entry_past_its_plan_expiry_is_cancelled_by_its_client_id() -> None:
    rig = await placed_rig()
    await move_past_expiry(rig)

    results = await run_once(rig, StoredExpiry(rig))

    (result,) = results
    assert result.outcome == OUTCOME_CANCELED and result.verdict is CancelVerdict.CANCELED
    assert result.plan_hash == rig.plan.plan_hash
    (cancel,) = rig.fake.calls_to("cancel_normal_order")
    assert cancel["kwargs"] == {"symbol": "BTCUSDT", "orig_client_order_id": rig.entry_id}
    assert rig.entry_id not in rig.fake.open_orders
    expiry_rows = rig.journal.by_type("ENTRY_EXPIRY")
    assert expiry_rows, "expire_pending_entry journals its pre and post images"
    assert all(
        json.loads(row.payload_json)["trigger_reason"] == "expiry_time" for row in expiry_rows
    )
    # Protective legs are never touched (T-24-62, WR-07 / G2-026).
    assert rig.fake.calls_to("cancel_algo_order") == []
    assert rig.fake.calls_to("place_algo_protective") == []
    assert len(rig.fake.calls_to("place_entry")) == 1


async def test_before_the_expiry_nothing_is_read_or_cancelled() -> None:
    rig = await placed_rig()
    reads_before = len(rig.fake.calls_to("query_order_by_client"))

    results = await run_once(rig, StoredExpiry(rig))

    assert results == ()
    assert rig.fake.calls_to("cancel_normal_order") == []
    assert len(rig.fake.calls_to("query_order_by_client")) == reads_before
    assert rig.entry_id in rig.fake.open_orders


async def test_at_exactly_the_expiry_instant_the_entry_is_cancelled() -> None:
    rig = await placed_rig()
    await move_past_expiry(rig, extra=0.0)
    assert rig.clock.now() == rig.plan.expiry_utc

    (result,) = await run_once(rig, StoredExpiry(rig))

    assert result.outcome == OUTCOME_CANCELED


# --------------------------------------------------------------------------- #
# Fills belong to the coordinator (T-24-61).
# --------------------------------------------------------------------------- #


async def test_a_partly_filled_entry_is_not_cancelled_and_is_journaled() -> None:
    rig = await placed_rig()
    rig.fake.fill(rig.entry_id, quantity=D("0.004"))
    await move_past_expiry(rig)

    (result,) = await run_once(rig, StoredExpiry(rig))

    assert result.outcome == OUTCOME_LEFT_TO_COORDINATOR and result.detail == "executed"
    assert rig.fake.calls_to("cancel_normal_order") == []
    assert rig.entry_id in rig.fake.open_orders, "the remainder still rests for the coordinator"
    (row,) = scheduled_rows(rig)
    payload = json.loads(row.payload_json)
    assert payload["outcome"] == OUTCOME_LEFT_TO_COORDINATOR and payload["reason"] == "executed"
    assert payload["symbol"] == "BTCUSDT" and row.entity_id == rig.plan.plan_hash


async def test_a_fully_filled_entry_is_left_to_the_coordinator() -> None:
    rig = await placed_rig()
    rig.fake.fill(rig.entry_id)
    await move_past_expiry(rig)

    (result,) = await run_once(rig, StoredExpiry(rig))

    assert result.outcome == OUTCOME_LEFT_TO_COORDINATOR
    assert rig.fake.calls_to("cancel_normal_order") == []


async def test_an_unknown_executed_quantity_is_not_read_as_zero() -> None:
    rig = await placed_rig()
    await move_past_expiry(rig)
    record = rig.fake.open_orders[rig.entry_id]
    original = rig.fake.query_order_by_client

    async def no_quantity(**kwargs: Any) -> Any:
        import dataclasses

        probe = await original(**kwargs)
        assert record.executed_quantity == 0
        return dataclasses.replace(probe, executed_quantity=None)

    rig.fake.query_order_by_client = no_quantity  # type: ignore[method-assign]

    (result,) = await run_once(rig, StoredExpiry(rig))

    assert result.outcome == OUTCOME_LEFT_TO_COORDINATOR and result.detail == "quantity_unknown"
    assert rig.fake.calls_to("cancel_normal_order") == []


async def test_an_entry_the_exchange_does_not_find_is_left_to_the_coordinator() -> None:
    rig = await placed_rig()
    await move_past_expiry(rig)
    rig.fake.open_orders.pop(rig.entry_id)  # neither open nor in the history

    (result,) = await run_once(rig, StoredExpiry(rig))

    assert result.outcome == OUTCOME_LEFT_TO_COORDINATOR and result.detail == "not_found"
    assert rig.fake.calls_to("cancel_normal_order") == []
    (row,) = scheduled_rows(rig)
    assert json.loads(row.payload_json)["reason"] == "not_found"


# --------------------------------------------------------------------------- #
# Failures never raise and never leak a message.
# --------------------------------------------------------------------------- #


async def test_a_failing_rest_read_cancels_nothing_and_is_journaled_by_class() -> None:
    rig = await placed_rig()
    await move_past_expiry(rig)
    rig.fake.fail_next("query_order_by_client", RuntimeError("https://x/?signature=abc123"))

    (result,) = await run_once(rig, StoredExpiry(rig))

    assert result.outcome == OUTCOME_READ_FAILED and result.detail == "RuntimeError"
    assert rig.fake.calls_to("cancel_normal_order") == []
    (row,) = scheduled_rows(rig)
    assert json.loads(row.payload_json)["error_class"] == "RuntimeError"
    assert all("signature" not in event.payload_json for event in rig.journal.calls)


async def test_a_failing_cancel_is_journaled_and_does_not_raise() -> None:
    rig = await placed_rig()
    await move_past_expiry(rig)
    rig.fake.fail_next("cancel_normal_order", RuntimeError("https://x/?signature=def456"))

    (result,) = await run_once(rig, StoredExpiry(rig))

    assert result.outcome == OUTCOME_CANCEL_FAILED and result.detail == "RuntimeError"
    assert len(rig.fake.calls_to("cancel_normal_order")) == 1, "no retry loop"
    assert rig.entry_id in rig.fake.open_orders
    assert all("signature" not in event.payload_json for event in rig.journal.calls)


async def test_a_missing_or_unreadable_stored_expiry_cancels_nothing() -> None:
    rig = await placed_rig()
    await move_past_expiry(rig)
    unknown = StoredExpiry(rig)
    unknown.unknown.add(rig.plan.plan_hash)

    (missing,) = await run_once(rig, unknown)
    (failing,) = await run_once(rig, StoredExpiry(rig, error=ConnectionError("db down")))

    assert missing.outcome == OUTCOME_EXPIRY_UNKNOWN and missing.detail == "no_expiry"
    assert failing.outcome == OUTCOME_EXPIRY_UNKNOWN and failing.detail == "ConnectionError"
    assert rig.fake.calls_to("cancel_normal_order") == []


async def test_a_naive_clock_value_is_refused_before_any_call() -> None:
    rig = await placed_rig()
    with pytest.raises(ValueError):
        await run_once(rig, StoredExpiry(rig), now=datetime(2030, 1, 1))
    assert rig.fake.calls_to("cancel_normal_order") == []


# --------------------------------------------------------------------------- #
# Idempotence and scope.
# --------------------------------------------------------------------------- #


async def test_a_second_run_after_a_successful_cancel_does_nothing() -> None:
    rig = await placed_rig()
    await move_past_expiry(rig)
    store = StoredExpiry(rig)
    first = await run_once(rig, store)
    rows_after_first = len(rig.journal.calls)

    (second,) = await run_once(rig, store)

    assert first[0].outcome == OUTCOME_CANCELED
    assert second.outcome == OUTCOME_NOT_RESTING
    assert len(rig.fake.calls_to("cancel_normal_order")) == 1
    assert len(rig.journal.calls) == rows_after_first, "a settled entry writes no new row"


async def test_a_plan_past_awaiting_fill_is_not_examined() -> None:
    rig = await placed_rig()
    rig.fake.fill(rig.entry_id, quantity=D("0.004"))
    assert rig.route(rig.trade_frame()).fills == 1
    await rig.wiring.coordinator.step()
    await move_past_expiry(rig)
    protection = rig.wiring.coordinator.protection_of(rig.plan.plan_hash)
    assert protection is not None and protection.state is not ProtectionState.AWAITING_FILL
    store = StoredExpiry(rig)
    reads_before = len(rig.fake.calls_to("query_order_by_client"))
    cancels_before = len(rig.fake.calls_to("cancel_normal_order"))  # the coordinator's own

    results = await run_once(rig, store)

    assert results == ()
    assert store.reads == 0
    assert len(rig.fake.calls_to("query_order_by_client")) == reads_before
    assert len(rig.fake.calls_to("cancel_normal_order")) == cancels_before


async def test_the_cancel_leaves_no_algo_order_untouched_in_the_book() -> None:
    """A stop that exists (after a fill) is still resting after the scheduled check ran."""
    rig = await placed_rig()
    rig.fake.fill(rig.entry_id, quantity=D("0.004"))
    rig.route(rig.trade_frame())
    await rig.wiring.coordinator.step()
    await rig.clock.advance(1)
    await rig.wiring.coordinator.step()
    stops = set(rig.fake.open_algos)
    assert stops
    await move_past_expiry(rig)

    await run_once(rig, StoredExpiry(rig))

    assert set(rig.fake.open_algos) == stops
    assert rig.fake.calls_to("cancel_algo_order") == []


# --------------------------------------------------------------------------- #
# Source rules (acceptance criteria).
# --------------------------------------------------------------------------- #


def test_the_module_names_no_protective_cancel_or_placement_call() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    for forbidden in ("cancel_algo", "place_algo_protective", "place_entry", "place_market_close"):
        assert forbidden not in text
    assert "expire_pending_entry(" in text
    assert "datetime.now" not in text and "time.time" not in text


# --------------------------------------------------------------------------- #
# Quick 261114-mp1 (D110): the resting entry of an unrestorable plan after a partial restore.
# --------------------------------------------------------------------------- #

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
HASH_B = "b" * 64
HASH_C = "c" * 64
SYMBOL_B = "ETHUSDT"


def entry_id(plan_hash: str) -> str:
    return derive_client_order_id(plan_hash=plan_hash, role=OrderRole.ENTRY.value)


def unrestored(
    plan_hash: str = HASH_B, symbol: str = SYMBOL_B, *, rebuilt: bool = False
) -> UnrestorableEntry:
    return UnrestorableEntry(
        trade_plan_id="TEST_ONLY_plan",
        approval_id="TEST_ONLY_approval",
        plan_hash=plan_hash,
        symbol=symbol,
        fault_class="RestoreSourceMissing",
        plan_hash_rebuilt=rebuilt,
    )


async def exchange_with_entry(
    plan_hash: str = HASH_B, symbol: str = SYMBOL_B
) -> BinanceSemanticsFakeAdapter:
    fake = BinanceSemanticsFakeAdapter()
    await fake.place_entry(
        symbol=symbol,
        side="BUY",
        position_side="BOTH",
        quantity=D("1"),
        price=D("100"),
        time_in_force="GTC",
        new_client_order_id=entry_id(plan_hash),
    )
    return fake


async def cancel_unrestored(
    fake: BinanceSemanticsFakeAdapter,
    entries: list[UnrestorableEntry],
    *,
    alerts: Any = None,
    journal: RecordingJournal | None = None,
) -> Any:
    return await cancel_unrestored_entries(
        entries=entries,
        adapter=fake,  # type: ignore[arg-type]
        journal=journal if journal is not None else RecordingJournal(),
        spill=None,
        alerts=alerts if alerts is not None else RecordingAlerts(),
        now_utc=NOW,
    )


async def test_an_unrestored_resting_entry_is_cancelled_once_by_its_client_id() -> None:
    fake = await exchange_with_entry()
    alerts = RecordingAlerts()
    journal = RecordingJournal()

    (result,) = await cancel_unrestored(fake, [unrestored()], alerts=alerts, journal=journal)

    assert result.outcome == OUTCOME_CANCELED and result.verdict is CancelVerdict.CANCELED
    assert result.plan_hash == HASH_B and result.symbol == SYMBOL_B
    (cancel,) = fake.calls_to("cancel_normal_order")
    assert cancel["kwargs"] == {"symbol": SYMBOL_B, "orig_client_order_id": entry_id(HASH_B)}
    assert entry_id(HASH_B) not in fake.open_orders
    assert len(fake.calls_to("snapshot_positions")) == 1, "one position read"
    assert alerts.alerts == []
    triggers = {
        json.loads(e.payload_json)["trigger_reason"]
        for e in journal.events
        if e.event_type == "ENTRY_EXPIRY"
    }
    assert triggers == {"protection_handoff_failed"}
    for forbidden in ("place_algo_protective", "place_market_close"):
        assert fake.calls_to(forbidden) == []
    assert len(fake.calls_to("place_entry")) == 1, "only the test's own setup placement"


async def test_a_cancel_that_raises_is_alerted_once_and_never_retried() -> None:
    fake = await exchange_with_entry()
    fake.fail_next("cancel_normal_order", RuntimeError("scripted"))
    alerts = RecordingAlerts()

    (result,) = await cancel_unrestored(fake, [unrestored()], alerts=alerts)

    assert len(fake.calls_to("cancel_normal_order")) == 1, "no second cancel"
    assert result.outcome == OUTCOME_CANCEL_FAILED and result.detail == "RuntimeError"
    (alert,) = alerts.alerts
    assert alert.event == "PROTECTION_HANDOFF_FAILED"
    assert alert.reason == REASON_UNRESTORED_CANCEL_FAILED
    assert alert.plan_hash == HASH_B and alert.symbol == SYMBOL_B and alert.now_utc == NOW
    assert entry_id(HASH_B) in fake.open_orders, "the entry is still resting: SAFE_MODE stays"


async def test_an_entry_the_exchange_does_not_find_is_an_unverified_cancel() -> None:
    fake = BinanceSemanticsFakeAdapter()  # nothing rests: the cancel answers absent
    alerts = RecordingAlerts()

    (result,) = await cancel_unrestored(fake, [unrestored()], alerts=alerts)

    assert result.verdict is CancelVerdict.UNKNOWN
    (alert,) = alerts.alerts
    assert alert.event == "PROTECTION_HANDOFF_FAILED"
    assert alert.reason == REASON_UNRESTORED_CANCEL_UNVERIFIED
    assert len(fake.calls_to("cancel_normal_order")) == 1


async def test_a_still_open_entry_after_the_cancel_is_an_unverified_cancel() -> None:
    fake = await exchange_with_entry()
    open_order = fake.open_orders[entry_id(HASH_B)]

    async def cancel_does_nothing(**kwargs: Any) -> None:
        fake.calls.append({"method": "cancel_normal_order", "kwargs": dict(kwargs)})

    fake.cancel_normal_order = cancel_does_nothing  # type: ignore[method-assign]
    alerts = RecordingAlerts()

    (result,) = await cancel_unrestored(fake, [unrestored()], alerts=alerts)

    assert open_order.status == "NEW" and result.verdict is CancelVerdict.STILL_OPEN
    (alert,) = alerts.alerts
    assert alert.reason == REASON_UNRESTORED_CANCEL_UNVERIFIED
    assert len(fake.calls_to("cancel_normal_order")) == 1


async def test_a_plan_hash_shared_with_a_rebuilt_plan_is_never_cancelled() -> None:
    fake = await exchange_with_entry()
    alerts = RecordingAlerts()

    (result,) = await cancel_unrestored(fake, [unrestored(rebuilt=True)], alerts=alerts)

    assert fake.calls_to("cancel_normal_order") == []
    assert result.outcome == OUTCOME_REFUSED
    assert entry_id(HASH_B) in fake.open_orders
    assert [a.reason for a in alerts.alerts[:1]] == [REASON_UNRESTORED_CANCEL_REFUSED]
    assert alerts.alerts[0].event == "PROTECTION_HANDOFF_FAILED"


async def test_a_symbol_outside_the_live_universe_is_refused_before_any_exchange_call() -> None:
    fake = await exchange_with_entry(symbol="DOGEUSDT")
    alerts = RecordingAlerts()

    (result,) = await cancel_unrestored(fake, [unrestored(symbol="DOGEUSDT")], alerts=alerts)

    assert fake.calls_to("cancel_normal_order") == []
    assert fake.calls_to("snapshot_positions") == [], "no position read for a refused symbol"
    assert result.outcome == OUTCOME_REFUSED
    assert [(a.event, a.reason) for a in alerts.alerts] == [
        ("PROTECTION_HANDOFF_FAILED", REASON_UNRESTORED_CANCEL_REFUSED),
        ("DIVERGENCE", REASON_UNRESTORED_POSITION_UNKNOWN),
    ]


async def test_a_position_read_that_raises_is_a_divergence_with_an_unknown_position() -> None:
    fake = await exchange_with_entry()
    fake.fail_next("snapshot_positions", RuntimeError("scripted"))
    alerts = RecordingAlerts()

    (result,) = await cancel_unrestored(fake, [unrestored()], alerts=alerts)

    assert result.outcome == OUTCOME_CANCELED
    assert result.position == REASON_UNRESTORED_POSITION_UNKNOWN
    (alert,) = alerts.alerts
    assert alert.event == "DIVERGENCE" and alert.reason == REASON_UNRESTORED_POSITION_UNKNOWN
    assert len(fake.calls_to("snapshot_positions")) == 1


async def test_a_non_zero_position_is_a_divergence_and_nothing_is_closed() -> None:
    fake = await exchange_with_entry()
    fake.fill(entry_id(HASH_B), quantity=D("0.4"))
    alerts = RecordingAlerts()

    (result,) = await cancel_unrestored(fake, [unrestored()], alerts=alerts)

    assert result.position == REASON_UNRESTORED_PLAN_POSITION
    (alert,) = alerts.alerts
    assert alert.event == "DIVERGENCE" and alert.reason == REASON_UNRESTORED_PLAN_POSITION
    assert fake.calls_to("place_market_close") == [] and fake.positions[SYMBOL_B] == D("0.4")


async def test_two_entries_with_the_same_plan_hash_cancel_once() -> None:
    fake = await exchange_with_entry()

    results = await cancel_unrestored(fake, [unrestored(), unrestored()])

    assert len(results) == 1
    assert len(fake.calls_to("cancel_normal_order")) == 1


async def test_two_distinct_plans_are_each_cancelled_once() -> None:
    fake = await exchange_with_entry(HASH_B)
    await fake.place_entry(
        symbol="SOLUSDT",
        side="BUY",
        position_side="BOTH",
        quantity=D("1"),
        price=D("100"),
        time_in_force="GTC",
        new_client_order_id=entry_id(HASH_C),
    )

    results = await cancel_unrestored(
        fake, [unrestored(HASH_B), unrestored(HASH_C, symbol="SOLUSDT")]
    )

    assert [r.plan_hash for r in results] == [HASH_B, HASH_C]
    assert len(fake.calls_to("cancel_normal_order")) == 2
    assert fake.open_orders == {}


class RaisingAlerts:
    """An alert sink that fails on every call (the next entry must still run)."""

    def __init__(self) -> None:
        self.calls = 0

    def critical(self, **kwargs: Any) -> None:
        self.calls += 1
        raise RuntimeError("sink down")


async def test_a_raising_alert_sink_does_not_stop_the_next_entry() -> None:
    fake = BinanceSemanticsFakeAdapter()  # both entries are absent: each one wants an alert
    sink = RaisingAlerts()

    results = await cancel_unrestored(fake, [unrestored(HASH_B), unrestored(HASH_C)], alerts=sink)

    assert len(results) == 2
    assert len(fake.calls_to("cancel_normal_order")) == 2
    assert sink.calls >= 2


class _Stop(BaseException):
    """A BaseException that is not an Exception (it must propagate)."""


async def test_a_base_exception_propagates() -> None:
    fake = await exchange_with_entry()
    fake.fail_next("cancel_normal_order", _Stop())

    with pytest.raises(_Stop):
        await cancel_unrestored(fake, [unrestored()])


def test_every_event_the_restart_cancel_uses_is_in_the_alert_contract() -> None:
    assert ALERT_EVENTS["PROTECTION_HANDOFF_FAILED"] is AlertSeverity.CRITICAL
    assert ALERT_EVENTS["DIVERGENCE"] is AlertSeverity.HIGH
    from src.ops.alerts import OperationalAlert

    for event, reason in (
        ("PROTECTION_HANDOFF_FAILED", REASON_UNRESTORED_CANCEL_UNVERIFIED),
        ("PROTECTION_HANDOFF_FAILED", REASON_UNRESTORED_CANCEL_FAILED),
        ("PROTECTION_HANDOFF_FAILED", REASON_UNRESTORED_CANCEL_REFUSED),
        ("DIVERGENCE", REASON_UNRESTORED_PLAN_POSITION),
        ("DIVERGENCE", REASON_UNRESTORED_POSITION_UNKNOWN),
    ):
        OperationalAlert.create(
            event=event,
            subject=SYMBOL_B,
            reason=reason,
            occurred_at_utc=NOW,
            plan_hash=HASH_B,
            symbol=SYMBOL_B,
        )


def test_the_restart_cancel_names_no_placement_or_close_call() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    assert "cancel_unrestored_entries" in text
    assert "float(" not in text and "tenacity" not in text
