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

Every sentence is traced to the emitting code in `tests/fixtures/phase23/DERIVATIONS.md`; a
sentence claims only what that code does. The branch codes below are literals: this module
imports nothing from `src.execution` (a test pins them equal to the `BRANCH_*` constants of
`src/execution/protection.py`, so a new branch without wording fails).

`RECONCILIATION_REQUIRED` is a wording-only outcome (it is a refusal reason of the execution
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

BRANCH_B1_ENTRY_NOT_TERMINAL = "B1_ENTRY_NOT_TERMINAL"
BRANCH_B2_STOP_UNCONFIRMED = "B2_STOP_UNCONFIRMED"
BRANCH_B3_BOTH_AMBIGUOUS = "B3_BOTH_AMBIGUOUS"
BRANCH_B4_FILL_AFTER_STOP = "B4_FILL_AFTER_STOP"
BRANCH_B5_STOP_REJECTED = "B5_STOP_REJECTED"
BRANCH_NO_POSITION_BUT_EXPOSED = "NO_POSITION_ON_STOP_BUT_EXPOSED"
BRANCH_B4_STOP_LOST_UNRESOLVED = "B4_STOP_LOST_UNRESOLVED"
BRANCH_OPERATOR_CLOSE = "OPERATOR_CLOSE"
BRANCH_B6_LIQUIDATION_TOO_CLOSE = "B6_LIQUIDATION_TOO_CLOSE"

# What the coordinator does on every entry into CLOSE_REQUIRED (protection.py
# `_enter_close_required` and `_record_close_required`): the plan blocks new entries, the
# emergency closer is called, then SAFE_MODE and the critical alert follow, whatever the close
# answered. A failed close raises its own alert.
_CLOSE_REQUIRED_SYSTEM = (
    "The plan moved to CLOSE_REQUIRED, new entries are blocked (SAFE_MODE CLOSE_REQUIRED) and "
    "a reduce-only MARKET emergency close was attempted; if that close fails, "
    "EMERGENCY_CLOSE_FAILED or EMERGENCY_CLOSE_NOT_SENT follows as its own alert."
)
_STOP_KEPT = "An open stop is kept until the position is flat; the stop is never cancelled here."
_CHECK_THEN_ACT = (
    "Check the exchange position and the journal before any manual action. "
    "If the position is still open, close it or protect it yourself."
)

CLOSE_REQUIRED_WORDING: MappingProxyType[str, AlertWording] = MappingProxyType(
    {
        BRANCH_B1_ENTRY_NOT_TERMINAL: AlertWording(
            what_happened=(
                "A position was filled and its stop is confirmed on the exchange, but the rest "
                "of the entry order was still open after the allowed time "
                "(B1_ENTRY_NOT_TERMINAL)."
            ),
            position=(
                "A position is open and has a confirmed stop; the unfilled rest of the entry "
                "may still fill."
            ),
            system_did=(
                _CLOSE_REQUIRED_SYSTEM + " " + _STOP_KEPT + " The cancel of the entry rest is "
                "issued again on each protection step. Closing a position that has a good stop "
                "for this reason is accepted knowingly and journaled."
            ),
            operator_must=(
                "Check on the exchange that the position is closed and the entry order is "
                "cancelled, and read the journal for B1_ENTRY_NOT_TERMINAL before any manual "
                "action."
            ),
        ),
        BRANCH_B2_STOP_UNCONFIRMED: AlertWording(
            what_happened=(
                "A position was filled but its stop was still not confirmed by the exchange "
                "after the allowed time, and the entry order is no longer open "
                "(B2_STOP_UNCONFIRMED)."
            ),
            position="A position may be open without a confirmed stop.",
            system_did=(
                _CLOSE_REQUIRED_SYSTEM + " Before this, the stop was queried by id on every "
                "step and re-placed only when the exchange proved it absent."
            ),
            operator_must=_CHECK_THEN_ACT,
        ),
        BRANCH_B3_BOTH_AMBIGUOUS: AlertWording(
            what_happened=(
                "A position was filled, its stop was still not confirmed by the exchange after "
                "the allowed time and the entry order is still open (B3_BOTH_AMBIGUOUS)."
            ),
            position=(
                "A position may be open without a confirmed stop, and the open entry may still "
                "fill and add to it."
            ),
            system_did=(
                _CLOSE_REQUIRED_SYSTEM + " Before this, the stop and the entry were queried by "
                "id on every step and the cancel of the entry was issued again on each step."
            ),
            operator_must=(
                "Check the exchange position, the open entry order and the journal before any "
                "manual action. Cancel the entry if it is still open, and close or protect any "
                "open position yourself."
            ),
        ),
        BRANCH_B4_FILL_AFTER_STOP: AlertWording(
            what_happened=(
                "A stop that was confirmed earlier is no longer active while a position exists "
                "(B4_FILL_AFTER_STOP)."
            ),
            position="A position is open and may have no active stop.",
            system_did=(
                _CLOSE_REQUIRED_SYSTEM + " The stop is never placed again for this reason; the "
                "rest of the entry is cancelled and the exposure is closed by MARKET."
            ),
            operator_must=_CHECK_THEN_ACT,
        ),
        BRANCH_B5_STOP_REJECTED: AlertWording(
            what_happened=(
                "The exchange definitively rejected the stop after the fill, and the stop was "
                "not sent again (B5_STOP_REJECTED)."
            ),
            position="A position is open without a stop.",
            system_did=(
                _CLOSE_REQUIRED_SYSTEM + " The stop intent was journaled as rejected and a "
                "PROTECTIVE_REJECTED alert with the same reason code was raised."
            ),
            operator_must=(
                "Check the exchange position and the journal for the rejection before any "
                "manual action. If the position is still open, close it yourself."
            ),
        ),
        BRANCH_NO_POSITION_BUT_EXPOSED: AlertWording(
            what_happened=(
                "The exchange refused the stop because it saw no position, but the position "
                "read that followed shows an open position "
                "(NO_POSITION_ON_STOP_BUT_EXPOSED)."
            ),
            position="A position is open without a stop.",
            system_did=_CLOSE_REQUIRED_SYSTEM,
            operator_must=_CHECK_THEN_ACT,
        ),
        BRANCH_B4_STOP_LOST_UNRESOLVED: AlertWording(
            what_happened=(
                "A stop that was confirmed earlier was lost, and the plan did not reach a safe "
                "state (position flat and entry ended) within the allowed time after the loss "
                "was first seen (B4_STOP_LOST_UNRESOLVED)."
            ),
            position=(
                "A position may be open without a stop; the position could not be read or the "
                "entry may still fill."
            ),
            system_did=(
                _CLOSE_REQUIRED_SYSTEM + " The stop was never placed again for this reason, and "
                "the emergency close reads the position quantity itself instead of sending a "
                "guessed one."
            ),
            operator_must=_CHECK_THEN_ACT,
        ),
        BRANCH_OPERATOR_CLOSE: AlertWording(
            what_happened="An operator asked to close this plan (OPERATOR_CLOSE).",
            position=("A position may be open; this message does not say whether it has a stop."),
            system_did=(
                _CLOSE_REQUIRED_SYSTEM + " " + _STOP_KEPT + " The close quantity is read from "
                "the exchange, never guessed."
            ),
            operator_must=(
                "Check on the exchange that the position is flat and read the journal for "
                "OPERATOR_CLOSE; if it is still open, close it yourself."
            ),
        ),
        BRANCH_B6_LIQUIDATION_TOO_CLOSE: AlertWording(
            what_happened=(
                "After the fill, the liquidation price of the position lies too close beyond "
                "the stop, or is unknown (B6_LIQUIDATION_TOO_CLOSE)."
            ),
            position=(
                "A position is open with a confirmed stop, but it may be liquidated before the "
                "stop is reached."
            ),
            system_did=_CLOSE_REQUIRED_SYSTEM + " " + _STOP_KEPT,
            operator_must=(
                "Check the exchange position, its liquidation price and the journal before any "
                "manual action. If the position is still open, close it or reduce the risk "
                "yourself."
            ),
        ),
    }
)

# Any CLOSE_REQUIRED reason that is not a branch code above (a future branch, or a sanitised
# INVALID_REASON). The header still carries the reason code.
CLOSE_REQUIRED_GENERIC = AlertWording(
    what_happened=(
        "The position of this plan must be closed (CLOSE_REQUIRED); the reason code in the "
        "header has no plain-word text yet."
    ),
    position="A position may be open and may have no confirmed stop.",
    system_did=_CLOSE_REQUIRED_SYSTEM,
    operator_must=_CHECK_THEN_ACT,
)

# --------------------------------------------------------------------------- #
# The other worded events.
# --------------------------------------------------------------------------- #

EVENT_WORDING: MappingProxyType[str, AlertWording] = MappingProxyType(
    {
        "TP_UNAVAILABLE": AlertWording(
            what_happened=(
                "The take profit orders could not be put in place after the entry was "
                "filled (TP_UNAVAILABLE); the reason code in the header says why."
            ),
            position=(
                "A position is open. Its stop is confirmed, but it has no confirmed take profit."
            ),
            system_did=(
                "The confirmed stop is kept and nothing is closed for this reason alone "
                "(no automatic flatten, no single take profit fallback). SAFE_MODE "
                "ENTRY_WITHOUT_PROTECTIVE blocks new entries."
            ),
            operator_must=(
                "Check the exchange position and confirm its stop is there. Decide yourself "
                "whether to place take profits or close; the system will not do it."
            ),
        ),
        "EMERGENCY_CLOSE_FAILED": AlertWording(
            what_happened=(
                "The automatic emergency close could not be shown to end with a flat position "
                "(EMERGENCY_CLOSE_FAILED); the reason code in the header says where it "
                "stopped."
            ),
            position="A position may still be open, with or without a stop.",
            system_did=(
                "SAFE_MODE EMERGENCY_CLOSE_FAILED blocks new entries and the failure is "
                "journaled. The position was not declared safe, and a second close order is "
                "never sent while the first is undetermined."
            ),
            operator_must=(
                "Check the exchange position now and close it yourself if it is still open; "
                "read the journal for the reason code."
            ),
        ),
        "EMERGENCY_CLOSE_NOT_SENT": AlertWording(
            what_happened=(
                "The emergency close was not sent: the request gate refused it before it left "
                "the system (EMERGENCY_CLOSE_NOT_SENT, PRE_SEND_REFUSED), for example during "
                "an exchange rate limit pause."
            ),
            position=(
                "A position may be open, with or without a stop. Nothing was sent, so the "
                "close has not happened."
            ),
            system_did=(
                "The refusal is journaled and kept as a pending close that carries no price or "
                "quantity. No safety is claimed; the next protection step reads the position "
                "again, and the unprotected deadline keeps running."
            ),
            operator_must=(
                "Check the exchange position now. If the pause blocks the system, close or "
                "protect the position yourself as soon as the exchange allows."
            ),
        ),
        "ENTRY_STATE_UNKNOWN": AlertWording(
            what_happened=(
                "The entry order was sent once and its result is not known: the exchange "
                "answer was unclear and one lookup by client order id did not settle it "
                "(ENTRY_STATE_UNKNOWN). This needs reconciliation."
            ),
            position=(
                "An entry order may be resting on the exchange and may fill, so a position may "
                "be open or may open."
            ),
            system_did=(
                "The entry was not re-sent and will not be. SAFE_MODE blocks new entries. The "
                "entry is kept as unknown and given to the protection step, which looks it up "
                "by client order id and places the stop if it finds a fill; a failed hand-off "
                "raises PROTECTION_HANDOFF_FAILED."
            ),
            operator_must=(
                "Check the exchange for this order and for a position on the symbol, and "
                "reconcile before any manual action. Do not approve the plan again."
            ),
        ),
        "PROTECTION_HANDOFF_FAILED": AlertWording(
            what_happened=(
                "The entry order could not be handed to the protection step that places the "
                "stop after a fill (PROTECTION_HANDOFF_FAILED)."
            ),
            position=(
                "The entry order may still rest on the exchange. If it fills, nothing in the "
                "system watches it or places a stop."
            ),
            system_did=(
                "SAFE_MODE blocks new entries, and the system tried to cancel the entry by its "
                "client order id; the result of that cancel is in the journal."
            ),
            operator_must=(
                "Check the exchange now: cancel the entry if it is still open, and protect or "
                "close any position that exists."
            ),
        ),
        "DB_FAILURE": AlertWording(
            what_happened=(
                "A database read or write the safety path depends on failed, or the stored day "
                "state is missing or unreadable (DB_FAILURE; the reason code is the SAFE_MODE "
                "reason, DAY_STATE_MISSING or DAY_STATE_UNREADABLE)."
            ),
            position=(
                "A position may be open. This message does not say whether it is protected, and "
                "the local records may be incomplete."
            ),
            system_did=(
                "New entries are blocked while the problem lasts. Nothing was cancelled or "
                "re-sent because of this message; stops and take profits are not touched."
            ),
            operator_must=(
                "Check the database and the journal using the reason code, and check the "
                "exchange positions and orders directly until the records are healthy again."
            ),
        ),
        # Plan 24-13 (W8 of 20-VERIFICATION). The header carries the until line of the ban.
        "REST_GATE_BAN_ENTERED": AlertWording(
            what_happened=(
                "The exchange banned the requests of this system (HTTP 418) and the REST gate "
                "now refuses every REST call before it is sent (REST_GATE_BAN_ENTERED, "
                "IP_BAN_418). The until line of the header is the gate's own end time of the "
                "ban."
            ),
            position=(
                "A position may be open, with or without a stop. While the ban lasts the system "
                "cannot read it or change it through REST."
            ),
            system_did=(
                "Until that time no REST call leaves the system, so nothing reaches the "
                "exchange meanwhile. The end time is saved, so a restart keeps the ban. A "
                "placement is never re-sent."
            ),
            operator_must=(
                "Check the exchange position and its stop yourself now, and close or protect "
                "the position if it needs it. Start no other traffic to the exchange from this "
                "address until the until time has passed."
            ),
        ),
        "REST_GATE_RECOVERY_REQUIRED": AlertWording(
            what_happened=(
                "The saved state of the REST gate (the ban and pause end times) was missing, "
                "unreadable or not trusted at start (REST_GATE_RECOVERY_REQUIRED, "
                "GATE_STATE_UNKNOWN), so the gate cannot tell whether a ban is active."
            ),
            position=(
                "A position may be open, with or without a stop. While the gate is in this "
                "state the system cannot read it or change it through REST."
            ),
            system_did=(
                "The gate refuses every REST call before it is sent, with no known end time, "
                "until a restart reads a valid saved state. Nothing reaches the exchange "
                "meanwhile, an emergency close included."
            ),
            operator_must=(
                "Check the exchange position and its stop yourself now, and close or protect "
                "the position if it needs it. Then clear the gate state as RUNBOOK section 21.3 "
                "describes."
            ),
        ),
        # Quick 261114-mp1 (D111). The subject line of the header names the task.
        "TASK_STALLED": AlertWording(
            what_happened=(
                "A live task has been running longer than its bound (TASK_STALLED, "
                "STALL_BOUND_EXCEEDED). The subject line of the header names the task."
            ),
            position=(
                "A position may be open, with or without a stop. While the protection step is "
                "stalled, a new fill may wait for its stop."
            ),
            system_did=(
                "The task was not stopped or restarted, nothing was cancelled and nothing was "
                "re-sent (a placement is never re-sent). The stall is recorded in the journal."
            ),
            operator_must=(
                "Check the process log and the exchange position and its stop now, and close or "
                "protect the position if it needs it. Restart the process if the task does not "
                "finish."
            ),
        ),
    }
)

# --------------------------------------------------------------------------- #
# RECONCILIATION_REQUIRED: the outcome of an approval, not an alert event.
# --------------------------------------------------------------------------- #

RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"

RECONCILIATION_REQUIRED_WORDING = AlertWording(
    what_happened=(
        "The result of this approval is not settled (RECONCILIATION_REQUIRED). It needs "
        "reconciliation with the exchange."
    ),
    position=(
        "An order or a position may exist on the exchange that the local record does not show."
    ),
    system_did=(
        "No order was re-sent for this approval (a placement is never re-sent) and no new entry "
        "is placed from this answer."
    ),
    operator_must=(
        "Check the exchange orders and positions for this symbol and wait for the "
        "reconciliation before any manual action. Do not approve the plan again."
    ),
)


def reconciliation_required_text() -> str:
    """The plain words for the outcome RECONCILIATION_REQUIRED (four lines, no header)."""
    return "\n".join(RECONCILIATION_REQUIRED_WORDING.lines())


# --------------------------------------------------------------------------- #
# Lookup and rendering.
# --------------------------------------------------------------------------- #


def wording_for(event: str, reason: str) -> AlertWording | None:
    """The wording of one alert, or None when the event has none (sent as before)."""
    if event == "CLOSE_REQUIRED":
        return CLOSE_REQUIRED_WORDING.get(reason, CLOSE_REQUIRED_GENERIC)
    return EVENT_WORDING.get(event)


def worded_alert_text(alert: OperationalAlert) -> str | None:
    """The Phase 20 header followed by the four wording lines, or None without wording."""
    wording = wording_for(alert.event, alert.reason)
    if wording is None:
        return None
    from src.ops.alerts import render_alert_text  # noqa: PLC0415 - alerts imports this module

    return "\n".join((render_alert_text(alert), *wording.lines()))
