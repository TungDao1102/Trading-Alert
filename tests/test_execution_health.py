"""Health-check probe tests (Phase 9, plan 09-04).

Per SECURITY_AND_OPERATIONS.md section 4: ten probes cover market-feed
freshness, last closed-candle time, WS connection state, user-data
stream state, REST error rate, reconciliation drift, database writes,
Telegram delivery, unprotected positions, and orphaned orders. Each
probe journals exactly one HEALTH_CHECK JournalEvent; a RED (FAIL)
result on any probe blocks the aggregate `run_health_checks` verdict.

The behaviors pinned here:

  1. All ten probes PASS yields an aggregate PASS verdict.
  2. Any single FAIL probe yields an aggregate NO_TRADE verdict with
     reason_code HEALTH_CHECK_FAILED (RED blocks enablement).
  3. Each probe journals exactly one HEALTH_CHECK JournalEvent carrying
     the check name and status.
  4. The ten canonical check names match the SECURITY_AND_OPERATIONS
     section 4 vocabulary, in order.
  5. The Telegram delivery probe PASSes on a successful send and FAILs
     on an exception or None response, without ever logging chat_id
     or probe text into the journal payload.
  6. Purity: src/ops/health.py imports stdlib + domain/journal only —
     no Binance SDK, no python-telegram-bot, no SQLAlchemy, no
     Pydantic, no Polars.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from src.domain.enums import KillGateState

NOW_UTC = datetime(2026, 9, 29, 10, 30, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# FakeJournal — records every event for byte-exact assertions.
# --------------------------------------------------------------------------- #


class FakeJournal:
    """In-memory journal that records every event."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    def record(self, event: Any) -> None:
        self.events.append(event)


class FakeNotifier:
    """In-memory Telegram-notify fake for the delivery probe."""

    def __init__(self, *, response: Any = "sent", raises: Exception | None = None) -> None:
        self._response = response
        self._raises = raises
        self.calls: list[dict[str, Any]] = []

    async def send_message(self, *, chat_id: Any, text: str, reply_markup: Any = None) -> Any:
        self.calls.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        if self._raises is not None:
            raise self._raises
        return self._response


# --------------------------------------------------------------------------- #
# Helper: run every probe with a PASS-shaped input set.
# --------------------------------------------------------------------------- #


def _run_all_probes_passing(journal: FakeJournal) -> list[Any]:
    from src.ops.health import (
        check_db_writes,
        check_last_closed_candle_time,
        check_market_feed_freshness,
        check_orphaned_orders,
        check_reconciliation_drift,
        check_rest_error_rate,
        check_unprotected_positions,
        check_user_data_stream_state,
        check_ws_connection_state,
    )

    return [
        check_market_feed_freshness(
            last_market_event_at_utc=NOW_UTC - timedelta(seconds=5),
            now_utc=NOW_UTC,
            staleness_threshold=timedelta(seconds=60),
            journal=journal,
        ),
        check_last_closed_candle_time(
            last_closed_candle_close_utc=NOW_UTC - timedelta(minutes=30),
            now_utc=NOW_UTC,
            expected_cadence=timedelta(hours=1),
            journal=journal,
        ),
        check_ws_connection_state(connected=True, now_utc=NOW_UTC, journal=journal),
        check_user_data_stream_state(connected=True, now_utc=NOW_UTC, journal=journal),
        check_rest_error_rate(
            error_count=0,
            total_count=100,
            max_error_rate=Decimal("0.05"),
            now_utc=NOW_UTC,
            journal=journal,
        ),
        check_reconciliation_drift(positions_reconciled=True, now_utc=NOW_UTC, journal=journal),
        check_db_writes(
            last_db_write_at_utc=NOW_UTC - timedelta(seconds=10),
            now_utc=NOW_UTC,
            staleness_threshold=timedelta(minutes=5),
            journal=journal,
        ),
        check_unprotected_positions(divergences=[], now_utc=NOW_UTC, journal=journal),
        check_orphaned_orders(divergences=[], now_utc=NOW_UTC, journal=journal),
    ]


# --------------------------------------------------------------------------- #
# Beh. 1 — all probes PASS yields aggregate PASS.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_all_probes_pass_yields_aggregate_pass_verdict() -> None:
    """Beh. 1: all ten probes PASS yields an aggregate PASS verdict."""
    from src.ops.health import check_telegram_delivery, run_health_checks

    journal = FakeJournal()
    results = _run_all_probes_passing(journal)
    telegram_result = await check_telegram_delivery(
        notifier=FakeNotifier(response={"message_id": 1}),
        chat_id=123456,
        probe_text="health-probe-ping",
        now_utc=NOW_UTC,
        journal=journal,
    )
    results.append(telegram_result)

    assert len(results) == 10, f"expected 10 probe results, got {len(results)}"

    verdict = run_health_checks(results=results)
    assert verdict.is_no_trade is False, f"expected PASS, got NO_TRADE: {verdict.reason_code}"
    assert verdict.reason_code == "OK"


# --------------------------------------------------------------------------- #
# Beh. 2 — any single FAIL probe yields aggregate NO_TRADE.
# --------------------------------------------------------------------------- #


def test_any_fail_probe_blocks_enablement_with_health_check_failed() -> None:
    """Beh. 2: a single RED (FAIL) probe yields NO_TRADE with reason
    code HEALTH_CHECK_FAILED — RED blocks enablement.
    """
    from src.ops.health import check_ws_connection_state, run_health_checks

    journal = FakeJournal()
    passing = _run_all_probes_passing(journal)
    # Force the WS connection probe to FAIL (disconnected).
    failing_ws = check_ws_connection_state(connected=False, now_utc=NOW_UTC, journal=journal)

    verdict = run_health_checks(results=[*passing, failing_ws])
    assert verdict.is_no_trade is True
    assert verdict.reason_code == "HEALTH_CHECK_FAILED"


# --------------------------------------------------------------------------- #
# Beh. 3 — each probe journals exactly one HEALTH_CHECK JournalEvent.
# --------------------------------------------------------------------------- #


def test_each_probe_journals_exactly_one_health_check_event() -> None:
    """Beh. 3: each probe call journals exactly one HEALTH_CHECK event
    carrying the check name and status.
    """
    from src.ops.health import ALL_CHECK_NAMES

    journal = FakeJournal()
    results = _run_all_probes_passing(journal)

    # 9 sync probes were run above (Telegram is async, tested separately).
    assert len(journal.events) == len(results)
    for event, result in zip(journal.events, results, strict=True):
        assert event.event_type == "HEALTH_CHECK"
        assert event.entity_id == result.check_name
        assert event.entity_id in ALL_CHECK_NAMES


# --------------------------------------------------------------------------- #
# Beh. 4 — canonical check-name vocabulary matches SECURITY_AND_OPERATIONS §4.
# --------------------------------------------------------------------------- #


def test_ten_canonical_check_names_in_order() -> None:
    """Beh. 4: the ten canonical check names match the
    SECURITY_AND_OPERATIONS section 4 vocabulary, in document order.
    """
    from src.ops.health import ALL_CHECK_NAMES

    assert len(ALL_CHECK_NAMES) == 10
    assert ALL_CHECK_NAMES == (
        "market_feed_freshness",
        "last_closed_candle_time",
        "ws_connection_state",
        "user_data_stream_state",
        "rest_error_rate",
        "reconciliation_drift",
        "db_writes",
        "telegram_delivery",
        "unprotected_positions",
        "orphaned_orders",
    )


# --------------------------------------------------------------------------- #
# Beh. 5 — Telegram delivery probe PASS/FAIL without logging secrets.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_telegram_delivery_probe_passes_on_successful_send() -> None:
    """Beh. 5a: a successful send_message yields PASS."""
    from src.ops.health import check_telegram_delivery

    journal = FakeJournal()
    notifier = FakeNotifier(response={"message_id": 42})

    result = await check_telegram_delivery(
        notifier=notifier,
        chat_id=987654,
        probe_text="health-probe-ping",
        now_utc=NOW_UTC,
        journal=journal,
    )

    assert result.status == "PASS"
    assert len(notifier.calls) == 1


@pytest.mark.asyncio
async def test_telegram_delivery_probe_fails_on_exception() -> None:
    """Beh. 5b: an exception from send_message yields FAIL, and the
    journal payload never contains the chat_id or probe text.
    """
    from src.ops.health import check_telegram_delivery

    journal = FakeJournal()
    notifier = FakeNotifier(raises=RuntimeError("simulated network failure"))

    result = await check_telegram_delivery(
        notifier=notifier,
        chat_id="secret-looking-chat-id-999",
        probe_text="health-probe-ping",
        now_utc=NOW_UTC,
        journal=journal,
    )

    assert result.status == "FAIL"
    assert len(journal.events) == 1
    payload = journal.events[0].payload_json
    assert "secret-looking-chat-id-999" not in payload
    assert "health-probe-ping" not in payload


@pytest.mark.asyncio
async def test_telegram_delivery_probe_fails_when_notifier_is_none() -> None:
    """Beh. 5c: no notifier configured yields FAIL (fail-closed)."""
    from src.ops.health import check_telegram_delivery

    journal = FakeJournal()

    result = await check_telegram_delivery(
        notifier=None,
        chat_id=123,
        probe_text="health-probe-ping",
        now_utc=NOW_UTC,
        journal=journal,
    )

    assert result.status == "FAIL"


# --------------------------------------------------------------------------- #
# Beh. 6 — unprotected-positions and orphaned-orders probes read divergences.
# --------------------------------------------------------------------------- #


def test_unprotected_positions_probe_fails_on_entry_without_protective_divergence() -> None:
    """Beh. 6a: an ENTRY_WITHOUT_PROTECTIVE divergence yields FAIL."""
    from src.ops.health import check_unprotected_positions

    journal = FakeJournal()
    divergences = [{"kind": "ENTRY_WITHOUT_PROTECTIVE", "symbol": "BTCUSDT"}]

    result = check_unprotected_positions(divergences=divergences, now_utc=NOW_UTC, journal=journal)
    assert result.status == "FAIL"


def test_orphaned_orders_probe_fails_on_orphan_protective_divergence() -> None:
    """Beh. 6b: an ORPHAN_PROTECTIVE divergence yields FAIL."""
    from src.ops.health import check_orphaned_orders

    journal = FakeJournal()
    divergences = [{"kind": "ORPHAN_PROTECTIVE", "symbol": "ETHUSDT"}]

    result = check_orphaned_orders(divergences=divergences, now_utc=NOW_UTC, journal=journal)
    assert result.status == "FAIL"


# --------------------------------------------------------------------------- #
# Beh. 7 — purity: no Binance SDK / PTB / SQLAlchemy / Pydantic / Polars imports.
# --------------------------------------------------------------------------- #


def test_health_module_purity() -> None:
    """Beh. 7: src/ops/health.py imports stdlib + domain/journal only."""
    import re
    from pathlib import Path

    module_path = Path(__file__).resolve().parents[1] / "src" / "ops" / "health.py"
    source = module_path.read_text(encoding="utf-8")
    forbidden_patterns = [
        r"\bimport\s+binance_sdk\b",
        r"\bfrom\s+binance_sdk\b",
        r"\bimport\s+telegram\b",
        r"\bfrom\s+telegram\b",
        r"\bimport\s+sqlalchemy\b",
        r"\bfrom\s+sqlalchemy\b",
        r"\bimport\s+pydantic\b",
        r"\bfrom\s+pydantic\b",
        r"\bimport\s+polars\b",
        r"\bfrom\s+polars\b",
    ]
    for pattern in forbidden_patterns:
        match = re.search(pattern, source)
        assert match is None, (
            f"forbidden import in {module_path}: pattern={pattern!r}, match={match.group(0)!r}"
        )


# --------------------------------------------------------------------------- #
# 09-REVIEW WR-08 — incomplete / duplicated probe sets never aggregate to OK.
# --------------------------------------------------------------------------- #


def test_partial_probe_set_is_health_check_failed() -> None:
    """WR-08: a lone PASS probe is not a healthy system."""
    from src.ops.health import check_ws_connection_state, run_health_checks

    journal = FakeJournal()
    verdict = run_health_checks(
        results=[check_ws_connection_state(connected=True, now_utc=NOW_UTC, journal=journal)]
    )
    assert verdict.is_no_trade is True
    assert verdict.reason_code == "HEALTH_CHECK_FAILED"


def test_duplicated_probe_masking_a_missing_one_is_health_check_failed() -> None:
    """WR-08: nine probes + a duplicate WS PASS (Telegram never ran)."""
    from src.ops.health import check_ws_connection_state, run_health_checks

    journal = FakeJournal()
    results = _run_all_probes_passing(journal)
    results.append(check_ws_connection_state(connected=True, now_utc=NOW_UTC, journal=journal))
    assert len(results) == 10
    verdict = run_health_checks(results=results)
    assert verdict.is_no_trade is True


def test_hand_built_partial_pass_verdict_is_rejected() -> None:
    """WR-08: a PASS HealthVerdict must be structurally complete."""
    from src.ops.health import HealthVerdict, check_ws_connection_state

    journal = FakeJournal()
    with pytest.raises(ValueError, match="PASS verdict requires"):
        HealthVerdict(
            is_no_trade=False,
            reason_code="OK",
            results=(check_ws_connection_state(connected=True, now_utc=NOW_UTC, journal=journal),),
        )


# --------------------------------------------------------------------------- #
# 09-REVIEW WR-09 — journal ids are content hashes (no same-ms PK collision).
# --------------------------------------------------------------------------- #


def test_same_probe_same_timestamp_different_result_gets_distinct_ids() -> None:
    from src.ops.health import check_ws_connection_state

    journal = FakeJournal()
    check_ws_connection_state(connected=True, now_utc=NOW_UTC, journal=journal)
    check_ws_connection_state(connected=False, now_utc=NOW_UTC, journal=journal)
    ids = [e.journal_event_id for e in journal.events]
    assert len(set(ids)) == 2
    assert all(i.startswith("health_check_") and len(i) <= 128 for i in ids)


def test_journal_ids_are_deterministic_for_identical_content() -> None:
    from src.ops.health import check_ws_connection_state

    first, second = FakeJournal(), FakeJournal()
    check_ws_connection_state(connected=True, now_utc=NOW_UTC, journal=first)
    check_ws_connection_state(connected=True, now_utc=NOW_UTC, journal=second)
    assert first.events[0].journal_event_id == second.events[0].journal_event_id


def test_enable_then_disable_in_same_millisecond_get_distinct_ids() -> None:
    from src.execution.enablement import LiveEnablementController
    from src.ops.health import ALL_CHECK_NAMES, HealthCheckResult, run_health_checks

    verdict = run_health_checks(
        results=[
            HealthCheckResult(check_name=n, status="PASS", detail="ok", observed_at_utc=NOW_UTC)
            for n in ALL_CHECK_NAMES
        ]
    )
    journal = FakeJournal()
    controller = LiveEnablementController(journal=journal)
    controller.enable(
        operator_id="op",
        now_utc=NOW_UTC,
        health_verdict=verdict,
        kill_gate_state=KillGateState.WITHIN_BUDGET,
    )
    controller.disable(operator_id="op", now_utc=NOW_UTC)
    controller.disable(operator_id="op", now_utc=NOW_UTC)
    ids = [e.journal_event_id for e in journal.events]
    assert len(set(ids)) == 3
