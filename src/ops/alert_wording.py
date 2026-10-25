"""Plain-word operator alerts (Phase 23, plan 23-03; CONTEXT D-14, 23-NOTES sections 1 and 3).

Phase 20 decides which alerts go out and keeps the sink, the dedupe and the bounded message
retry (`src/ops/alerts.py`). This module owns only WHAT the message says. An `OperationalAlert`
carries an event, a severity, an enum-like subject and reason, a time, a plan hash and a symbol,
so the words come from a static table keyed by the event (and, for CLOSE_REQUIRED, by the branch
code in the reason), never from free text.

A worded alert is the unchanged Phase 20 header (`render_alert_text`: severity, event, subject,
reason, UTC time) followed by four lines: what happened, whether a position may be open or
unprotected, what the system already did, and what the operator must do. The Phase 20 event and
reason codes stay verbatim in the header and in the sentences, so they can be searched in the
journal. An event without wording is sent exactly as before.

Every sentence is traced to the emitting code in `tests/fixtures/phase23/DERIVATIONS.md`. The
branch codes below are literals: this module imports nothing from `src.execution` (a test pins
them equal to the `BRANCH_*` constants of `src/execution/protection.py`).

`RECONCILIATION_REQUIRED` is a wording-only outcome (it is a rejection reason of the execution
outcome, not an alert event): `reconciliation_required_text` is for the DEMO/LIVE card and its
replies (plans 23-11 and 23-12) and is NOT in `ALERT_EVENTS`.

The module reads no clock and has no I/O. `render_alert_text` is imported inside
`worded_alert_text` because `src/ops/alerts.py` imports this module at the top (no cycle).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.ops.alerts import OperationalAlert

# Characters a wording line must not carry (T-23-10): nothing that looks like a secret, a mention
# or a URL can come out of a static table.
_FORBIDDEN_IN_WORDING = ("=", "@", "://")

_WHAT = "What happened: "
_POSITION = "Position: "
_SYSTEM = "System already did: "
_OPERATOR = "You must: "


@dataclass(frozen=True)
class AlertWording:
    """The four plain-word lines of one alert. Each field is one non-empty line of text."""

    what_happened: str
    position: str
    system_did: str
    operator_must: str

    def __post_init__(self) -> None:
        for value in (self.what_happened, self.position, self.system_did, self.operator_must):
            if not value or value != value.strip() or "\n" in value or "\r" in value:
                raise ValueError("a wording field is one non-empty line")
            if any(token in value for token in _FORBIDDEN_IN_WORDING):
                raise ValueError("a wording field carries a forbidden character sequence")

    def lines(self) -> tuple[str, str, str, str]:
        """The four prefixed lines, in the order the operator reads them."""
        return (
            _WHAT + self.what_happened,
            _POSITION + self.position,
            _SYSTEM + self.system_did,
            _OPERATOR + self.operator_must,
        )


# --------------------------------------------------------------------------- #
# CLOSE_REQUIRED: one wording per branch code of src/execution/protection.py.
# --------------------------------------------------------------------------- #

BRANCH_B2_STOP_UNCONFIRMED = "B2_STOP_UNCONFIRMED"

_CLOSE_REQUIRED_SYSTEM = (
    "The plan moved to CLOSE_REQUIRED, new entries are blocked (SAFE_MODE CLOSE_REQUIRED) and "
    "a reduce-only MARKET emergency close was attempted; a close that does not end flat raises "
    "EMERGENCY_CLOSE_FAILED."
)

CLOSE_REQUIRED_WORDING: MappingProxyType[str, AlertWording] = MappingProxyType(
    {
        BRANCH_B2_STOP_UNCONFIRMED: AlertWording(
            what_happened=(
                "A position was filled but its stop was still not confirmed by the exchange "
                "after the allowed time, and the entry order is no longer open "
                "(B2_STOP_UNCONFIRMED)."
            ),
            position="A position may be open without a confirmed stop.",
            system_did=(
                _CLOSE_REQUIRED_SYSTEM + " Before this, the stop was queried by id on every step "
                "and re-placed only when the exchange proved it absent."
            ),
            operator_must=(
                "Check the exchange position and the journal before any manual action. "
                "If the position is still open, close it or protect it yourself."
            ),
        ),
    }
)

EVENT_WORDING: MappingProxyType[str, AlertWording] = MappingProxyType({})


def wording_for(event: str, reason: str) -> AlertWording | None:
    """The wording of one alert, or None when the event has none (sent as before)."""
    if event == "CLOSE_REQUIRED":
        return CLOSE_REQUIRED_WORDING.get(reason)
    return EVENT_WORDING.get(event)


def worded_alert_text(alert: OperationalAlert) -> str | None:
    """The Phase 20 header followed by the four wording lines, or None without wording."""
    wording = wording_for(alert.event, alert.reason)
    if wording is None:
        return None
    from src.ops.alerts import render_alert_text  # noqa: PLC0415 - alerts imports this module

    return "\n".join((render_alert_text(alert), *wording.lines()))
