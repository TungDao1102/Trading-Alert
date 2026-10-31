"""The sweeper reads "cancel sent, absent from the open-algo list" as success (plan 24-21; D-34).

Demo finding (criterion 5): right after an algo cancel the by-id query still answers NEW for about
a second while the open-algo list is already empty. The Binance-semantics fake models it with
`algo_cancel_query_lag`; the sweeper then must not read the cancel as a failure (no skip, no second
cancel, no SAFE_MODE escalation). With no lag every older behaviour is unchanged, and a cancel that
really did not take effect (the id is still in the open list) stays `cancel_unverified`.

Evidence label: executed tests with the Binance-semantics fake; no network.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from src.execution.order_ids import derive_algo_client_id

from tests.support.fake_binance_exchange import BinanceSemanticsFakeAdapter
from tests.support.reconcile_doubles import RecordingJournal

NOW = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
SYMBOL = "BTCUSDT"
SL_ID = derive_algo_client_id(plan_hash="c" * 64, role="STOP_LOSS")
LAG = timedelta(seconds=1)


async def _place_leg(fake: BinanceSemanticsFakeAdapter, client_algo_id: str) -> None:
    await fake.place_algo_protective(
        symbol=SYMBOL,
        side="SELL",
        algo_type="CONDITIONAL",
        type="STOP_MARKET",
        position_side="BOTH",
        trigger_price=Decimal("59000"),
        close_position=True,
        quantity=None,
        working_type="MARK_PRICE",
        client_algo_id=client_algo_id,
        reduce_only=None,
    )


def _orphan_diff(*algo_ids: str) -> Any:
    from src.reconcile.compare import CompareDiff, OrphanProtective

    return CompareDiff(
        agreement=False,
        divergences=(),
        orphan_protectives=tuple(
            OrphanProtective(symbol=SYMBOL, client_algo_id=a, order_role="STOP_LOSS")
            for a in algo_ids
        ),
    )


def _flat(fake: BinanceSemanticsFakeAdapter) -> Any:
    def read(*, symbol: str) -> Decimal:
        return fake.positions.get(symbol, Decimal("0"))

    return read


def _sweeper(fake: Any, journal: Any) -> Any:
    from src.reconcile.sweeper import OrphanSweeper

    return OrphanSweeper(adapter=fake, journal=journal, now_utc=NOW)


def _payloads(journal: RecordingJournal, event_type: str) -> list[dict[str, Any]]:
    return [json.loads(e.payload_json) for e in journal.events if e.event_type == event_type]


# --------------------------------------------------------------------------- #
# The lagging fake.
# --------------------------------------------------------------------------- #


async def test_the_fake_answers_new_for_the_lag_after_a_cancel_while_the_list_is_empty() -> None:
    fake = BinanceSemanticsFakeAdapter(now_utc=NOW, algo_cancel_query_lag=LAG)
    await _place_leg(fake, SL_ID)

    await fake.cancel_algo_order(symbol=SYMBOL, client_algo_id=SL_ID)

    assert await fake.snapshot_open_algo_orders(symbol=SYMBOL) == []
    lagging = await fake.query_algo_order_by_client(client_algo_id=SL_ID)
    assert lagging.found is True and lagging.algo_status == "NEW"
    fake.now_utc = NOW + LAG - timedelta(milliseconds=1)
    assert (await fake.query_algo_order_by_client(client_algo_id=SL_ID)).algo_status == "NEW"
    fake.now_utc = NOW + LAG
    settled = await fake.query_algo_order_by_client(client_algo_id=SL_ID)
    assert settled.algo_status == "CANCELED"


async def test_the_default_lag_is_zero_and_the_answer_is_canceled_at_once() -> None:
    fake = BinanceSemanticsFakeAdapter(now_utc=NOW)
    await _place_leg(fake, SL_ID)

    await fake.cancel_algo_order(symbol=SYMBOL, client_algo_id=SL_ID)

    assert fake.algo_cancel_query_lag == timedelta(0)
    assert (await fake.query_algo_order_by_client(client_algo_id=SL_ID)).algo_status == "CANCELED"


async def test_a_lag_does_not_touch_an_algo_the_exchange_triggered() -> None:
    fake = BinanceSemanticsFakeAdapter(now_utc=NOW, algo_cancel_query_lag=LAG)
    await _place_leg(fake, SL_ID)

    fake.trigger_stop(SL_ID)

    assert (await fake.query_algo_order_by_client(client_algo_id=SL_ID)).algo_status == "FINISHED"


# --------------------------------------------------------------------------- #
# The sweeper.
# --------------------------------------------------------------------------- #


async def test_a_lagging_by_id_query_after_the_cancel_is_still_a_swept_orphan() -> None:
    fake = BinanceSemanticsFakeAdapter(now_utc=NOW, algo_cancel_query_lag=LAG)
    await _place_leg(fake, SL_ID)
    journal = RecordingJournal()

    outcome = await _sweeper(fake, journal).sweep(
        _orphan_diff(SL_ID), position_verifier=_flat(fake)
    )

    assert outcome.cancelled == ((SYMBOL, SL_ID),) and outcome.skipped == ()
    assert outcome.swept_count == 1
    assert len(fake.calls_to("cancel_algo_order")) == 1, "no second cancel"
    assert _payloads(journal, "SWEEP_SKIPPED") == [], "no SWEEP_SKIPPED row"
    phases = [p["phase"] for p in _payloads(journal, "ORPHAN_SWEEP")]
    assert phases == ["pre_cancel", "post_cancel"]
    post = _payloads(journal, "ORPHAN_SWEEP")[-1]
    assert post["verified_by"] == "open_algo_list" and post["verdict"] == "STILL_OPEN"
    assert len(fake.calls_to("snapshot_open_algo_orders")) == 1


async def test_without_a_lag_the_sweep_is_unchanged_and_reads_no_open_list() -> None:
    fake = BinanceSemanticsFakeAdapter(now_utc=NOW)
    await _place_leg(fake, SL_ID)
    journal = RecordingJournal()

    outcome = await _sweeper(fake, journal).sweep(
        _orphan_diff(SL_ID), position_verifier=_flat(fake)
    )

    assert outcome.cancelled == ((SYMBOL, SL_ID),)
    assert fake.calls_to("snapshot_open_algo_orders") == []
    post = _payloads(journal, "ORPHAN_SWEEP")[-1]
    assert post["verdict"] == "CANCELED" and "verified_by" not in post


class _StickyFake(BinanceSemanticsFakeAdapter):
    """The cancel call returns but the order keeps resting (a cancel that did not take effect)."""

    async def cancel_algo_order(self, **kwargs: Any) -> Any:  # type: ignore[override]
        self.calls.append({"method": "cancel_algo_order", "kwargs": dict(kwargs)})
        return None


async def test_a_cancel_that_did_not_take_effect_is_still_unverified() -> None:
    fake = _StickyFake(now_utc=NOW, algo_cancel_query_lag=LAG)
    await _place_leg(fake, SL_ID)
    journal = RecordingJournal()

    outcome = await _sweeper(fake, journal).sweep(
        _orphan_diff(SL_ID), position_verifier=_flat(fake)
    )

    assert outcome.swept_count == 0
    assert [s.reason for s in outcome.skipped] == ["cancel_unverified: STILL_OPEN"]
    assert len(_payloads(journal, "SWEEP_SKIPPED")) == 1


async def test_an_unreadable_open_list_keeps_the_cancel_unverified() -> None:
    fake = BinanceSemanticsFakeAdapter(now_utc=NOW, algo_cancel_query_lag=LAG)
    await _place_leg(fake, SL_ID)
    fake.fail_next("snapshot_open_algo_orders", RuntimeError("https://x/?signature=ab12"))
    journal = RecordingJournal()

    outcome = await _sweeper(fake, journal).sweep(
        _orphan_diff(SL_ID), position_verifier=_flat(fake)
    )

    assert outcome.swept_count == 0
    assert [s.reason for s in outcome.skipped] == ["cancel_unverified: STILL_OPEN"]
    assert all("signature" not in e.payload_json for e in journal.events)


async def test_an_adapter_without_the_open_list_read_keeps_the_older_rule() -> None:
    class Narrow:
        def __init__(self) -> None:
            self.cancels = 0

        async def query_algo_order_by_client(self, *, client_algo_id: str) -> Any:
            from src.adapters.binance_usdm import AlgoOrderProbe

            return AlgoOrderProbe(
                client_algo_id=client_algo_id, found=True, algo_status="NEW", update_time_utc=NOW
            )

        async def cancel_algo_order(self, *, symbol: str, client_algo_id: str) -> None:
            self.cancels += 1

    adapter = Narrow()
    journal = RecordingJournal()

    outcome = await _sweeper(adapter, journal).sweep(
        _orphan_diff(SL_ID), position_verifier=lambda *, symbol: Decimal("0")
    )

    assert adapter.cancels == 1 and outcome.swept_count == 0
    assert [s.reason for s in outcome.skipped] == ["cancel_unverified: STILL_OPEN"]
