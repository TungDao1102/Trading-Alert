"""Plain-word operator alerts (Phase 23, plan 23-03; CONTEXT D-14, 23-NOTES sections 1 and 3).

Evidence label: executed tests, pure functions of the static wording table. No Telegram call.

Task 1 (tracer): a CLOSE_REQUIRED B2_STOP_UNCONFIRMED alert becomes the unchanged Phase 20 header
plus four plain-word lines.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from src.execution import protection
from src.ops.alert_wording import (
    CLOSE_REQUIRED_GENERIC,
    CLOSE_REQUIRED_WORDING,
    EVENT_WORDING,
    RECONCILIATION_REQUIRED,
    AlertWording,
    reconciliation_required_text,
    worded_alert_text,
)
from src.ops.alerts import ALERT_EVENTS, OperationalAlert, render_alert_text

from tests.support.ast_guards import forbidden_imports, wall_clock_calls

T0= datetime(2026, 10, 9, 3, 0, 0, tzinfo=UTC)
PREFIXES = ("What happened: ", "Position: ", "System already did: ", "You must: ")


def _alert(event: str, reason: str, *, subject: str = "plan-0001") -> OperationalAlert:
    return OperationalAlert.create(
        event=event,
        subject=subject,
        reason=reason,
        occurred_at_utc=T0,
        plan_hash="a" * 64,
        symbol="BTCUSDT",
    )


def test_b2_close_required_is_the_header_plus_four_plain_lines() -> None:
    alert = _alert("CLOSE_REQUIRED", "B2_STOP_UNCONFIRMED")

    text = worded_alert_text(alert)

    assert text is not None
    header = render_alert_text(alert)
    assert text.startswith(header + "\n")
    lines = text[len(header) + 1 :].split("\n")
    assert len(lines) == 4
    for line, prefix in zip(lines, PREFIXES, strict=True):
        assert line.startswith(prefix)
        assert len(line) > len(prefix)


def test_b2_wording_says_what_the_emitting_code_does() -> None:
    text = worded_alert_text(_alert("CLOSE_REQUIRED", "B2_STOP_UNCONFIRMED"))

    assert text is not None
    lowered = text.lower()
    assert "B2_STOP_UNCONFIRMED" in text  # the code stays searchable in the journal
    assert "may be open" in lowered and "stop" in lowered
    assert "SAFE_MODE" in text
    assert "emergency close" in lowered
    assert "check" in lowered and "journal" in lowered


def test_an_event_without_wording_is_not_worded() -> None:
    assert worded_alert_text(_alert("STALE_DATA", "STALE_FEED")) is None


def test_the_wording_value_is_four_single_lines() -> None:
    wording = AlertWording("a", "b", "c", "d")

    assert wording.lines() == (
        "What happened: a",
        "Position: b",
        "System already did: c",
        "You must: d",
    )


# --------------------------------------------------------------------------- #
# Task 2: the full table, the reconciliation wording, code-equality pins.
# --------------------------------------------------------------------------- #

WORDING_SOURCE = Path(__file__).resolve().parents[1] / "src" / "ops" / "alert_wording.py"
SIX_EVENTS = {
    "TP_UNAVAILABLE",
    "EMERGENCY_CLOSE_FAILED",
    "EMERGENCY_CLOSE_NOT_SENT",
    "ENTRY_STATE_UNKNOWN",
    "PROTECTION_HANDOFF_FAILED",
    "DB_FAILURE",
}
TELEGRAM_MESSAGE_LIMIT = 4096


def _protection_branch_codes() -> set[str]:
    """Every BRANCH_* value of the coordinator, collected by name prefix in the test only."""
    return {
        value
        for name, value in vars(protection).items()
        if name.startswith("BRANCH_") and isinstance(value, str)
    }


def _all_entries() -> list[tuple[str, str, AlertWording]]:
    entries = [("CLOSE_REQUIRED", code, w) for code, w in CLOSE_REQUIRED_WORDING.items()]
    entries.append(("CLOSE_REQUIRED", "SOME_UNLISTED_REASON", CLOSE_REQUIRED_GENERIC))
    entries.extend((event, event, w) for event, w in EVENT_WORDING.items())
    return entries


def test_the_branch_literals_equal_the_coordinator_branch_constants_exactly() -> None:
    assert set(CLOSE_REQUIRED_WORDING) == _protection_branch_codes()
    assert len(_protection_branch_codes()) == 9


def test_every_event_wording_key_is_an_alert_event_and_the_six_are_worded() -> None:
    assert set(EVENT_WORDING) == SIX_EVENTS
    assert set(EVENT_WORDING) <= set(ALERT_EVENTS)
    assert "CLOSE_REQUIRED" in ALERT_EVENTS  # worded by branch code, not by EVENT_WORDING


def test_an_unlisted_close_required_reason_gets_the_generic_wording() -> None:
    alert = _alert("CLOSE_REQUIRED", "SOME_UNLISTED_REASON")

    text = worded_alert_text(alert)

    assert text == "\n".join((render_alert_text(alert), *CLOSE_REQUIRED_GENERIC.lines()))
    assert "CLOSE_REQUIRED" in "\n".join(CLOSE_REQUIRED_GENERIC.lines())


@pytest.mark.parametrize(("event", "reason", "wording"), _all_entries())
def test_every_entry_is_four_clean_single_lines_below_the_telegram_limit(
    event: str, reason: str, wording: AlertWording
) -> None:
    alert = _alert(event, reason)
    text = worded_alert_text(alert)

    assert text is not None
    assert len(text) < TELEGRAM_MESSAGE_LIMIT
    assert text.startswith(render_alert_text(alert) + "\n")
    lines = wording.lines()
    assert len(lines) == 4
    for line, prefix in zip(lines, PREFIXES, strict=True):
        assert line.startswith(prefix) and "\n" not in line
        assert not any(token in line for token in ("=", "@", "://"))


@pytest.mark.parametrize("code", sorted(CLOSE_REQUIRED_WORDING))
def test_each_branch_wording_carries_its_code_and_says_what_the_system_did(code: str) -> None:
    wording = CLOSE_REQUIRED_WORDING[code]

    assert code in wording.what_happened  # the journal code, verbatim
    joined = "\n".join(wording.lines())
    assert "CLOSE_REQUIRED" in joined and "SAFE_MODE" in joined
    assert "emergency close" in joined.lower() or "reduce-only" in joined.lower()
    assert "check" in wording.operator_must.lower()


@pytest.mark.parametrize("event", sorted(SIX_EVENTS))
def test_each_event_wording_carries_its_event_code(event: str) -> None:
    joined = "\n".join(EVENT_WORDING[event].lines())

    assert event in joined
    assert "check" in EVENT_WORDING[event].operator_must.lower()


def test_entry_state_unknown_says_needs_reconciliation_not_rejected_and_not_resent() -> None:
    joined = "\n".join(EVENT_WORDING["ENTRY_STATE_UNKNOWN"].lines())
    lowered = joined.lower()

    assert "needs reconciliation" in lowered
    assert "reject" not in lowered  # T-23-09: an ambiguous entry is never called rejected
    assert "not re-sent" in lowered
    assert "SAFE_MODE" in joined
    assert "exchange" in EVENT_WORDING["ENTRY_STATE_UNKNOWN"].operator_must.lower()


def test_reconciliation_required_is_wording_only() -> None:
    text = reconciliation_required_text()
    lowered = text.lower()

    assert RECONCILIATION_REQUIRED == "RECONCILIATION_REQUIRED"
    assert RECONCILIATION_REQUIRED in text
    assert "needs reconciliation" in lowered
    assert "reject" not in lowered
    assert "\n" in text and len(text) < TELEGRAM_MESSAGE_LIMIT
    assert RECONCILIATION_REQUIRED not in ALERT_EVENTS
    assert RECONCILIATION_REQUIRED not in EVENT_WORDING


def test_a_close_that_keeps_the_stop_says_so() -> None:
    # The coordinator never cancels an open stop when it enters CLOSE_REQUIRED (protection.py).
    for code in ("B1_ENTRY_NOT_TERMINAL", "B6_LIQUIDATION_TOO_CLOSE", "OPERATOR_CLOSE"):
        assert "stop is kept" in CLOSE_REQUIRED_WORDING[code].system_did.lower()


def test_db_failure_wording_is_true_for_the_daily_stop_emitter_too() -> None:
    joined = "\n".join(EVENT_WORDING["DB_FAILURE"].lines())

    # daily_stop.py raises DB_FAILURE with DAY_STATE_MISSING / DAY_STATE_UNREADABLE, enters no
    # SAFE_MODE and cancels nothing, so no sentence may claim otherwise.
    assert "DAY_STATE_MISSING" in joined and "DAY_STATE_UNREADABLE" in joined
    assert "nothing was cancelled" in joined.lower()


def test_the_module_imports_nothing_from_the_execution_layer_and_reads_no_clock() -> None:
    assert forbidden_imports(WORDING_SOURCE, ("src.execution", "src.reconcile")) == []
    assert wall_clock_calls(WORDING_SOURCE) == []


def test_the_alert_contract_of_phase_20_is_untouched() -> None:
    assert len(ALERT_EVENTS) == 20
    alert = _alert("CLOSE_REQUIRED", "B2_STOP_UNCONFIRMED")
    assert render_alert_text(alert) == (
        "[CRITICAL] CLOSE_REQUIRED\nsubject: plan-0001\nreason: B2_STOP_UNCONFIRMED\n"
        "at: 2026-10-09T03:00:00Z"
    )
