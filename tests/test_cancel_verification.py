"""A cancel is not counted until Binance shows it (Phase 20, plan 20-11, D-17, F-502).

Binance answers a cancel of an order that is no longer open with -2011 ("unknown order"), and the
adapter maps that answer to `None`, the same value a real cancel returns. For an entry the answer
can mean FILLED. So a cancel result proves nothing: only a query after the cancel does.

Evidence label: executed tests with the Binance-semantics fake and small scripted adapters; no
network, no Binance. The -2011 semantics are [DOC]; manual-close behavior on Binance is
[NOT_TESTED] (Phase 25).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from src.execution.order_ids import derive_algo_client_id, derive_client_order_id

from tests.support.ast_guards import float_constructor_calls, wall_clock_calls
from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
from tests.support.reconcile_doubles import RecordingJournal

NOW_UTC = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
PLAN_HASH = "5" * 64
SYMBOL = "BTCUSDT"
ENTRY_ID = derive_client_order_id(plan_hash=PLAN_HASH, role="ENTRY")
SL_ID = derive_algo_client_id(plan_hash=PLAN_HASH, role="STOP_LOSS")
TP1_ID = derive_algo_client_id(plan_hash=PLAN_HASH, role="TAKE_PROFIT_1")
TP2_ID = derive_algo_client_id(plan_hash=PLAN_HASH, role="TAKE_PROFIT_2")
SRC_ROOT = Path(__file__).parent.parent / "src"

QUANTITY = Decimal("0.004")
PRICE = Decimal("60000")


def _phases(journal: RecordingJournal) -> list[tuple[str, str]]:
    return [(e.entity_id, json.loads(e.payload_json)["phase"]) for e in journal.events]


async def _resting_entry(fake: BinanceSemanticsFakeAdapter) -> None:
    await fake.place_entry(
        symbol=SYMBOL,
        side="BUY",
        position_side="BOTH",
        time_in_force="GTC",
        quantity=QUANTITY,
        price=PRICE,
        new_client_order_id=ENTRY_ID,
    )


async def _expire(fake: BinanceSemanticsFakeAdapter, journal: RecordingJournal) -> Any:
    from src.execution.manager import expire_pending_entry

    return await expire_pending_entry(
        plan_hash=PLAN_HASH,
        symbol=SYMBOL,
        adapter=fake,  # type: ignore[arg-type]
        journal=journal,
        now_utc=NOW_UTC,
        trigger_reason="expiry_time",
    )


# --------------------------------------------------------------------------- #
# Task 1 (tracer): expire_pending_entry end to end.
# --------------------------------------------------------------------------- #


async def test_absent_cancel_of_a_filled_entry_is_not_canceled() -> None:
    """D-17, F-502: the entry filled, so the cancel answers absent (None); it was NOT canceled."""
    from src.execution.cancel_verification import CancelVerdict

    fake = BinanceSemanticsFakeAdapter()
    await _resting_entry(fake)
    fake.fill(ENTRY_ID)
    journal = RecordingJournal()

    verdict = await _expire(fake, journal)

    assert verdict is CancelVerdict.FILLED_OR_PARTIAL
    assert [c["method"] for c in fake.calls if c["method"].startswith("cancel")] == [
        "cancel_normal_order"
    ]
    assert fake.calls_to("query_order_by_client")  # the post-cancel query ran
    assert _phases(journal) == [(ENTRY_ID, "pre_cancel"), (ENTRY_ID, "cancel_unverified")]
    payload = json.loads(journal.events[-1].payload_json)
    assert payload["verdict"] == "FILLED_OR_PARTIAL"
    assert payload["observed_status"] == "FILLED"
    assert all(phase != "post_cancel" for _, phase in _phases(journal))


async def test_a_resting_entry_cancel_is_verified_and_journals_post_cancel() -> None:
    from src.execution.cancel_verification import CancelVerdict

    fake = BinanceSemanticsFakeAdapter()
    await _resting_entry(fake)
    journal = RecordingJournal()

    verdict = await _expire(fake, journal)

    assert verdict is CancelVerdict.CANCELED
    assert _phases(journal) == [(ENTRY_ID, "pre_cancel"), (ENTRY_ID, "post_cancel")]
    assert "verdict" not in json.loads(journal.events[-1].payload_json)


async def test_a_partially_filled_entry_that_ends_canceled_is_canceled_not_unknown() -> None:
    """Binance ends a partly filled entry CANCELED with its executed quantity kept (D-17)."""
    from src.execution.cancel_verification import CancelVerdict

    fake = BinanceSemanticsFakeAdapter()
    await _resting_entry(fake)
    fake.fill(ENTRY_ID, quantity=Decimal("0.001"))
    journal = RecordingJournal()

    assert await _expire(fake, journal) is CancelVerdict.CANCELED
    assert fake.positions[SYMBOL] == Decimal("0.001")  # the position it opened stays


async def test_a_failing_post_cancel_query_is_unknown_and_journals_the_error_type_only() -> None:
    from src.execution.cancel_verification import CancelVerdict

    fake = BinanceSemanticsFakeAdapter()
    await _resting_entry(fake)
    fake.fail_next("query_order_by_client", RuntimeError("signature=SECRET-TOKEN-123"))
    journal = RecordingJournal()

    verdict = await _expire(fake, journal)

    assert verdict is CancelVerdict.UNKNOWN
    assert _phases(journal) == [(ENTRY_ID, "pre_cancel"), (ENTRY_ID, "cancel_unverified")]
    event = journal.events[-1]
    payload = json.loads(event.payload_json)
    assert payload["verdict"] == "UNKNOWN"
    assert payload["error_type"] == "RuntimeError"
    assert "SECRET-TOKEN-123" not in event.payload_json


async def test_not_found_right_after_a_cancel_is_unknown_not_proof() -> None:
    """The entry is absent from both books (as after the 3-day retention): UNKNOWN, no claim."""
    from src.execution.cancel_verification import CancelVerdict

    fake = BinanceSemanticsFakeAdapter()  # nothing was ever placed: cancel -> None, query -> absent
    journal = RecordingJournal()

    verdict = await _expire(fake, journal)

    assert verdict is CancelVerdict.UNKNOWN
    assert _phases(journal)[-1] == (ENTRY_ID, "cancel_unverified")


async def test_a_failing_cancel_is_still_journaled_as_cancel_failed_and_reraised() -> None:
    fake = BinanceSemanticsFakeAdapter()
    await _resting_entry(fake)
    fake.fail_next("cancel_normal_order", RuntimeError("network"))
    journal = RecordingJournal()

    with pytest.raises(RuntimeError):
        await _expire(fake, journal)

    assert _phases(journal) == [(ENTRY_ID, "pre_cancel"), (ENTRY_ID, "cancel_failed")]
    assert fake.calls_to("query_order_by_client") == []  # no verification of a failed cancel


# --------------------------------------------------------------------------- #
# The verdict mapping.
# --------------------------------------------------------------------------- #


class _ScriptedAdapter:
    """Answers the two query methods with a scripted probe, or raises."""

    def __init__(self, entry: Any = None, algo: Any = None, boom: BaseException | None = None):
        self._entry, self._algo, self._boom = entry, algo, boom

    async def query_order_by_client(self, *, symbol: str, orig_client_order_id: str) -> Any:
        if self._boom is not None:
            raise self._boom
        return self._entry

    async def query_algo_order_by_client(self, *, client_algo_id: str) -> Any:
        if self._boom is not None:
            raise self._boom
        return self._algo


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("CANCELED", "CANCELED"),
        ("FILLED", "FILLED_OR_PARTIAL"),
        ("PARTIALLY_FILLED", "FILLED_OR_PARTIAL"),
        ("EXPIRED", "GONE_NOT_CANCELED"),
        ("EXPIRED_IN_MATCH", "GONE_NOT_CANCELED"),
        ("NEW", "STILL_OPEN"),
        ("PENDING_CANCEL", "UNKNOWN"),
        ("REJECTED", "UNKNOWN"),
        ("canceled", "UNKNOWN"),
        (None, "UNKNOWN"),
        (7, "UNKNOWN"),
    ],
)
async def test_confirm_entry_cancel_maps_every_status(status: Any, expected: str) -> None:
    from src.execution.cancel_verification import confirm_entry_cancel

    adapter = _ScriptedAdapter(entry=SimpleNamespace(found=True, status=status))
    verdict = await confirm_entry_cancel(adapter, symbol=SYMBOL, client_order_id=ENTRY_ID)
    assert verdict.value == expected


@pytest.mark.parametrize("found", [False, None, "yes", 1])
async def test_confirm_entry_cancel_needs_found_true(found: Any) -> None:
    from src.execution.cancel_verification import CancelVerdict, confirm_entry_cancel

    adapter = _ScriptedAdapter(entry=SimpleNamespace(found=found, status="CANCELED"))
    verdict = await confirm_entry_cancel(adapter, symbol=SYMBOL, client_order_id=ENTRY_ID)
    assert verdict is CancelVerdict.UNKNOWN


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("CANCELED", "CANCELED"),
        ("NEW", "STILL_OPEN"),
        ("TRIGGERING", "GONE_NOT_CANCELED"),
        ("TRIGGERED", "GONE_NOT_CANCELED"),
        ("FINISHED", "GONE_NOT_CANCELED"),
        ("REJECTED", "GONE_NOT_CANCELED"),
        ("EXPIRED", "GONE_NOT_CANCELED"),
        ("SOMETHING_NEW", "UNKNOWN"),
        ("new", "UNKNOWN"),
        (None, "UNKNOWN"),
    ],
)
async def test_confirm_algo_cancel_maps_every_status(status: Any, expected: str) -> None:
    from src.execution.cancel_verification import confirm_algo_cancel

    adapter = _ScriptedAdapter(algo=SimpleNamespace(found=True, algo_status=status))
    verdict = await confirm_algo_cancel(adapter, client_algo_id=SL_ID)
    assert verdict.value == expected


async def test_confirm_algo_cancel_absent_means_nothing_rests_there_not_a_cancel() -> None:
    """No algo order answers to the id: it is gone, but nothing proves WE canceled it."""
    from src.execution.cancel_verification import CancelVerdict, confirm_algo_cancel

    adapter = _ScriptedAdapter(algo=SimpleNamespace(found=False, algo_status=None))
    assert (
        await confirm_algo_cancel(adapter, client_algo_id=SL_ID) is CancelVerdict.GONE_NOT_CANCELED
    )


async def test_confirm_algo_cancel_found_not_a_bool_is_unknown() -> None:
    from src.execution.cancel_verification import CancelVerdict, confirm_algo_cancel

    adapter = _ScriptedAdapter(algo=SimpleNamespace(found=None, algo_status="CANCELED"))
    assert await confirm_algo_cancel(adapter, client_algo_id=SL_ID) is CancelVerdict.UNKNOWN


async def test_confirm_never_raises_and_a_missing_query_method_is_unknown() -> None:
    from src.execution.cancel_verification import (
        CancelDetail,
        CancelVerdict,
        confirm_algo_cancel,
        confirm_entry_cancel,
    )

    boom = _ScriptedAdapter(boom=ConnectionError("https://x/?signature=abc"))
    detail = CancelDetail()
    assert (
        await confirm_entry_cancel(boom, symbol=SYMBOL, client_order_id=ENTRY_ID, detail=detail)
        is CancelVerdict.UNKNOWN
    )
    assert detail.error_type == "ConnectionError"
    assert "signature" not in repr(detail)
    assert await confirm_algo_cancel(boom, client_algo_id=SL_ID) is CancelVerdict.UNKNOWN
    # An adapter without the query method at all (AttributeError) is also UNKNOWN.
    assert await confirm_algo_cancel(object(), client_algo_id=SL_ID) is CancelVerdict.UNKNOWN


async def test_a_cancelled_task_is_not_swallowed_by_confirm() -> None:
    import asyncio

    from src.execution.cancel_verification import confirm_entry_cancel

    adapter = _ScriptedAdapter(boom=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await confirm_entry_cancel(adapter, symbol=SYMBOL, client_order_id=ENTRY_ID)


def test_cancel_verification_reads_no_wall_clock_and_builds_no_float() -> None:
    path = SRC_ROOT / "execution" / "cancel_verification.py"
    assert wall_clock_calls(path) == []
    assert float_constructor_calls(path) == []
