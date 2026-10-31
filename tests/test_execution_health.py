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
# G2-035 (D-35), 09-REVIEW IN-07 — impossible counters and a False send result fail closed.
# --------------------------------------------------------------------------- #


def test_rest_error_rate_refuses_more_errors_than_requests_as_a_fail_result() -> None:
    """IN-07: error_count above total_count is a FAIL result, not a pass, not a rate above 1."""
    from src.ops.health import check_rest_error_rate

    journal = FakeJournal()
    result = check_rest_error_rate(
        error_count=5,
        total_count=3,
        max_error_rate=Decimal("2"),
        now_utc=NOW_UTC,
        journal=journal,
    )
    assert result.status == "FAIL"
    assert result.check_name == "rest_error_rate"
    assert len(journal.events) == 1


def test_rest_error_rate_with_errors_equal_to_requests_keeps_the_rate_result() -> None:
    """IN-07 boundary: error_count equal to total_count is a rate of 1, judged against the max."""
    from src.ops.health import check_rest_error_rate

    journal = FakeJournal()
    over = check_rest_error_rate(
        error_count=3,
        total_count=3,
        max_error_rate=Decimal("0.05"),
        now_utc=NOW_UTC,
        journal=journal,
    )
    assert over.status == "FAIL"
    assert "exceeds max" in over.detail
    within = check_rest_error_rate(
        error_count=3,
        total_count=3,
        max_error_rate=Decimal("1"),
        now_utc=NOW_UTC,
        journal=journal,
    )
    assert within.status == "PASS"


@pytest.mark.asyncio
async def test_telegram_delivery_probe_fails_when_the_send_result_is_false() -> None:
    """IN-07: a False send result is not a delivery."""
    from src.ops.health import check_telegram_delivery

    result = await check_telegram_delivery(
        notifier=FakeNotifier(response=False),
        chat_id=987654,
        probe_text="health-probe-ping",
        now_utc=NOW_UTC,
        journal=FakeJournal(),
    )
    assert result.status == "FAIL"


def test_health_verdict_reason_code_is_the_enum_value_byte_for_byte() -> None:
    """G3-005 (D-35): the failing verdict emits RejectionReason.HEALTH_CHECK_FAILED.value."""
    from src.domain.enums import RejectionReason
    from src.ops.health import check_ws_connection_state, run_health_checks

    journal = FakeJournal()
    verdict = run_health_checks(
        results=[check_ws_connection_state(connected=False, now_utc=NOW_UTC, journal=journal)]
    )
    assert verdict.reason_code == RejectionReason.HEALTH_CHECK_FAILED.value
    assert verdict.reason_code == "HEALTH_CHECK_FAILED"


# --------------------------------------------------------------------------- #
# Beh. 7 — purity: no Binance SDK / PTB / SQLAlchemy / Pydantic / Polars imports.
# --------------------------------------------------------------------------- #


def test_health_module_purity() -> None:
    """Beh. 7: src/ops/health.py imports stdlib + domain/journal and domain/enums only."""
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


# --------------------------------------------------------------------------- #
# Plan 24-22 (D-26, DECISIONS D056) - the DEGRADED rows, per runtime mode.
# --------------------------------------------------------------------------- #


def _results_with_degraded(degraded: tuple[str, ...]) -> list[Any]:
    """Ten results: PASS everywhere except the named checks, which are DEGRADED."""
    from src.ops.health import ALL_CHECK_NAMES, HealthCheckResult

    return [
        HealthCheckResult(
            check_name=name,
            status="DEGRADED" if name in degraded else "PASS",
            detail="not applicable" if name in degraded else "ok",
            observed_at_utc=NOW_UTC,
        )
        for name in ALL_CHECK_NAMES
    ]


def test_d056_demo_degraded_passes_only_with_the_explicit_flag() -> None:
    from src.ops.health import HealthRuntimeMode, run_health_checks

    results = _results_with_degraded(("last_closed_candle_time",))
    allowed = run_health_checks(
        results=results, mode=HealthRuntimeMode.DEMO, demo_degraded_allowed=True
    )
    assert allowed.is_no_trade is False
    assert allowed.reason_code == "OK"
    assert allowed.mode is HealthRuntimeMode.DEMO
    assert allowed.demo_degraded_allowed is True
    assert allowed.degraded_names == ("last_closed_candle_time",)

    refused = run_health_checks(results=results, mode=HealthRuntimeMode.DEMO)
    assert refused.is_no_trade is True
    assert refused.reason_code == "HEALTH_CHECK_FAILED"
    assert refused.demo_degraded_allowed is False


def test_d056_live_degraded_is_never_ok_whatever_the_caller_hopes() -> None:
    from src.ops.health import HealthRuntimeMode, run_health_checks

    results = _results_with_degraded(("last_closed_candle_time",))
    verdict = run_health_checks(results=results, mode=HealthRuntimeMode.LIVE)
    assert verdict.is_no_trade is True
    assert verdict.reason_code == "HEALTH_CHECK_FAILED"
    assert verdict.mode is HealthRuntimeMode.LIVE


def test_d056_the_demo_flag_can_never_be_set_in_live_or_without_a_mode() -> None:
    from src.ops.health import HealthRuntimeMode, run_health_checks

    results = _results_with_degraded(("last_closed_candle_time",))
    with pytest.raises(ValueError, match="demo_degraded_allowed"):
        run_health_checks(results=results, mode=HealthRuntimeMode.LIVE, demo_degraded_allowed=True)
    with pytest.raises(ValueError, match="demo_degraded_allowed"):
        run_health_checks(results=results, demo_degraded_allowed=True)
    with pytest.raises(TypeError):
        run_health_checks(  # type: ignore[arg-type]
            results=results, mode=HealthRuntimeMode.DEMO, demo_degraded_allowed="yes"
        )


def test_d056_the_mode_accepts_the_binance_environment_values_and_nothing_else() -> None:
    from src.adapters.binance_client import Environment
    from src.ops.health import HealthRuntimeMode, run_health_checks

    results = _results_with_degraded(())
    assert run_health_checks(results=results, mode=Environment.DEMO).mode is HealthRuntimeMode.DEMO
    assert run_health_checks(results=results, mode=Environment.LIVE).mode is HealthRuntimeMode.LIVE
    with pytest.raises(ValueError):
        run_health_checks(results=results, mode=Environment.TESTNET)
    with pytest.raises(ValueError):
        run_health_checks(results=results, mode="demo")


def test_d056_a_fail_or_a_missing_name_is_not_ok_in_either_mode() -> None:
    from src.ops.health import (
        ALL_CHECK_NAMES,
        HealthCheckResult,
        HealthRuntimeMode,
        run_health_checks,
    )

    for mode in (HealthRuntimeMode.DEMO, HealthRuntimeMode.LIVE):
        flag = mode is HealthRuntimeMode.DEMO
        failing = [
            HealthCheckResult(
                check_name=name,
                status="FAIL" if name == "db_writes" else "PASS",
                detail="x",
                observed_at_utc=NOW_UTC,
            )
            for name in ALL_CHECK_NAMES
        ]
        assert run_health_checks(results=failing, mode=mode, demo_degraded_allowed=flag).is_no_trade
        assert run_health_checks(
            results=failing[:-1], mode=mode, demo_degraded_allowed=flag
        ).is_no_trade


def test_d056_a_hand_built_ok_verdict_cannot_smuggle_a_degraded_result() -> None:
    from src.ops.health import HealthRuntimeMode, HealthVerdict

    results = tuple(_results_with_degraded(("last_closed_candle_time",)))
    for mode, flag in (
        (HealthRuntimeMode.LIVE, False),
        (HealthRuntimeMode.DEMO, False),
    ):
        with pytest.raises(ValueError, match="DEGRADED"):
            HealthVerdict(
                is_no_trade=False,
                reason_code="OK",
                results=results,
                mode=mode,
                demo_degraded_allowed=flag,
            )
    with pytest.raises(ValueError, match="demo_degraded_allowed"):
        HealthVerdict(
            is_no_trade=False,
            reason_code="OK",
            results=tuple(_results_with_degraded(())),
            mode=HealthRuntimeMode.LIVE,
            demo_degraded_allowed=True,
        )


def test_d056_the_legacy_call_without_a_mode_keeps_its_old_result_for_the_rehearsal() -> None:
    """Plan 24-22 hand-off: scripts/demo_rehearsal.py still calls without a mode until plan 24-29.

    That call is the old behavior (DEGRADED passes) and its verdict carries no mode, so
    `enable_demo` of the live process refuses it (tests/test_live_enablement_wiring.py).
    """
    from src.ops.health import run_health_checks

    verdict = run_health_checks(results=_results_with_degraded(("ws_connection_state",)))
    assert verdict.is_no_trade is False
    assert verdict.mode is None
    assert verdict.demo_degraded_allowed is False


def test_d056_the_unchanged_policy_sentence_is_gone() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "src" / "ops" / "health.py").read_text(
        encoding="utf-8"
    )
    assert "unchanged policy" not in source


def test_d056_the_only_production_caller_passes_the_mode() -> None:
    """Every `run_health_checks(` call under src passes `mode=` (the live producer)."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src"
    callers: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", getattr(node.func, "attr", None))
                == "run_health_checks"
            ):
                callers.add(path.relative_to(root).as_posix())
                assert "mode" in {k.arg for k in node.keywords}, path
    assert callers == {"live/health.py"}


def test_not_applicable_result_is_degraded_and_journaled() -> None:
    from src.ops.health import CHECK_LAST_CLOSED_CANDLE_TIME, check_not_applicable

    journal = FakeJournal()
    result = check_not_applicable(
        check_name=CHECK_LAST_CLOSED_CANDLE_TIME,
        detail="not applicable to the live process",
        now_utc=NOW_UTC,
        journal=journal,
    )
    assert result.status == "DEGRADED"
    assert len(journal.events) == 1
    assert journal.events[0].event_type == "HEALTH_CHECK"


def test_health_check_event_payload_without_extra_is_byte_identical_to_the_probe_event() -> None:
    from src.ops.health import check_ws_connection_state, health_check_event

    journal = FakeJournal()
    result = check_ws_connection_state(connected=True, now_utc=NOW_UTC, journal=journal)
    assert health_check_event(result) == journal.events[0]
    enriched = health_check_event(result, extra={"python_version": "3.13", "mode": "DEMO"})
    assert enriched.payload_json != journal.events[0].payload_json
    assert '"python_version":"3.13"' in enriched.payload_json
    assert enriched.journal_event_id != journal.events[0].journal_event_id


def test_telegram_observed_delivery_probe() -> None:
    from src.ops.health import check_telegram_delivery_observed

    journal = FakeJournal()
    never = check_telegram_delivery_observed(
        last_delivery_ok=None, now_utc=NOW_UTC, journal=journal
    )
    ok = check_telegram_delivery_observed(last_delivery_ok=True, now_utc=NOW_UTC, journal=journal)
    bad = check_telegram_delivery_observed(last_delivery_ok=False, now_utc=NOW_UTC, journal=journal)
    assert (never.status, ok.status, bad.status) == ("FAIL", "PASS", "FAIL")
    assert never.check_name == "telegram_delivery"
