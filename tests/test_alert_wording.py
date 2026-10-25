"""Plain-word operator alerts (Phase 23, plan 23-03; CONTEXT D-14, 23-NOTES sections 1 and 3).

Evidence label: executed tests, pure functions of the static wording table. No Telegram call.

Task 1 (tracer): a CLOSE_REQUIRED B2_STOP_UNCONFIRMED alert becomes the unchanged Phase 20 header
plus four plain-word lines.
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.ops.alert_wording import AlertWording, worded_alert_text
from src.ops.alerts import OperationalAlert, render_alert_text

T0 = datetime(2026, 10, 9, 3, 0, 0, tzinfo=UTC)
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
