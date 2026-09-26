"""Three-way attribution vocabulary for paper records (Phase 7, plan 07-03).

Per D-03: every paper record carries an attribution field that splits
the outcome into one of three canonical kinds:

  - `system`: the engine emitted the record (signal, plan, NO_TRADE).
  - `user-executed-sim`: a SIMULATE fill leg with the approval-delay
    lag applied to the simulated `acted_at_utc`. This is the
    "what would have happened if the user had approved" leg.
  - `opportunity`: a skipped or expired plan retained with a reason
    code. Per D-03 (never-dropped rule), these rows are never
    dropped to flatter the record — absence of evidence is itself
    evidence.

The `str, Enum` mixin keeps ORM/JSON `.value` storage trivial while
preserving Enum identity for mypy checks. The values are byte-exact
and must not be renamed — Phase-10 analytics reads them.

FLAGGED ASSUMPTION (PAPER-02 unclassified): the approval-delay lag
constant `APPROVAL_DELAY_LAG_SECONDS` is a fixed documented value
modeling the user-executed-sim leg. It is calibrated against measured
Telegram latency in Phase 10, never blocking Phase 7. The constant
lives here (not in journal.py) because it is part of the attribution
vocabulary, not the assembly contract.
"""

from __future__ import annotations

from enum import Enum


class AttributionKind(str, Enum):
    """Canonical three-way attribution for paper records (D-03).

    Values are byte-exact: `system`, `user-executed-sim`, `opportunity`.
    No synonyms, no invented names — an unknown value is a load-time
    error. Phase-10 analytics reads these values directly.
    """

    SYSTEM = "system"
    USER_EXECUTED_SIM = "user-executed-sim"
    OPPORTUNITY = "opportunity"


# Approval-delay lag constant (FLAGGED ASSUMPTION, PAPER-02 unclassified).
# Models the user-executed-sim leg: the simulated approval `acted_at_utc`
# equals `signal.detected_at_utc + APPROVAL_DELAY_LAG_SECONDS`. Calibrated
# against measured Telegram latency in Phase 10, never blocking Phase 7.
# The value is a documented constant — not an env var — so a mid-soak
# change is a code change, not a config drift.
APPROVAL_DELAY_LAG_SECONDS: int = 30


__all__ = ["AttributionKind", "APPROVAL_DELAY_LAG_SECONDS"]
