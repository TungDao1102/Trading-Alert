"""Documented vocabulary and classification of the Binance algo-order status.

Vocabulary (plan 18-03): the seven documented values of the `X` field of
the user-data `ALGO_UPDATE` event, listed on the Binance "Algo Order Update"
section (read 2026-10-16 as a WebFetch summary, not character-exact and not
verified live; docs/SOURCES.md "Facts read for Phase 18").

Classification (plan 18-06, CONTEXT D-07, G2-028): every status has exactly
one class ACTIVE, TERMINAL_OK, TERMINAL_FAILED or UNKNOWN. The classes of
TRIGGERING, TRIGGERED, FINISHED and CANCELED are the owner's recorded
decision (`.planning/phases/18-user-data-stream-error-taxonomy/decisions/
18-DEC-O-18-01.md`, 2026-10-16: all four UNKNOWN, not confirmed protection
until independently verified through Binance; D055 is not decided here).
NEW, REJECTED and EXPIRED keep their documented meaning (NEW ACTIVE,
REJECTED and EXPIRED TERMINAL_FAILED). An unseen, empty, None, non-string or
wrong-case status is UNKNOWN, never ACTIVE (fail closed).

Only ACTIVE confirms protection (`is_protection_confirmed`): the attach path
of `src/execution/manager.py` confirms a protective leg and adopts an
existing leg through it. Reconcile and sweeper decisions driven by the class
are Phase 20; the sweeper only journals the class for diagnosis.

Pure: standard library only, no wall clock, no float. A status outside the
vocabulary is never coerced: the stream parser turns it into an
UNKNOWN_ALGO_STATUS anomaly (fail closed, D-05). Whether the REST
`algoStatus` vocabulary equals this set is UNVERIFIED (research F3; a probe
capture); a REST-only value classifies as UNKNOWN.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

ALGO_STATUS_VOCABULARY: frozenset[str] = frozenset(
    {
        "NEW",
        "TRIGGERING",
        "TRIGGERED",
        "FINISHED",
        "CANCELED",
        "REJECTED",
        "EXPIRED",
    }
)


def is_known_algo_status(value: object) -> bool:
    """True only for an exact (case-sensitive) member of `ALGO_STATUS_VOCABULARY`.

    None, the empty string, another case, surrounding whitespace and any
    non-string value are all False.
    """
    return isinstance(value, str) and value in ALGO_STATUS_VOCABULARY


class AlgoStatusClass(str, Enum):
    """The four D-07 classes of an algo-order status."""

    ACTIVE = "ACTIVE"
    TERMINAL_OK = "TERMINAL_OK"
    TERMINAL_FAILED = "TERMINAL_FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class AlgoStatusEntry:
    """One row of the classification table.

    `meaning` is the documented meaning (SOURCES.md "Facts read for Phase
    18", WebFetch summary); `source_note` names where the class comes from.
    """

    status: str
    klass: AlgoStatusClass
    meaning: str
    source_note: str


_RECORD = "decisions/18-DEC-O-18-01.md"
_DOCUMENTED = "documented meaning, no judgment flagged"

_ENTRIES: tuple[AlgoStatusEntry, ...] = (
    AlgoStatusEntry(
        status="NEW",
        klass=AlgoStatusClass.ACTIVE,
        meaning=("The conditional order was successfully placed but has not yet been triggered."),
        source_note=f"{_DOCUMENTED}; the record's default (NEW is ACTIVE), {_RECORD}",
    ),
    AlgoStatusEntry(
        status="TRIGGERING",
        klass=AlgoStatusClass.UNKNOWN,
        meaning=(
            "The order has met the triggering condition and has been forwarded to the "
            "matching engine."
        ),
        source_note=f"{_RECORD} line 'class TRIGGERING: UNKNOWN' (2026-10-16)",
    ),
    AlgoStatusEntry(
        status="TRIGGERED",
        klass=AlgoStatusClass.UNKNOWN,
        meaning="The order has been successfully placed into the matching engine.",
        source_note=f"{_RECORD} line 'class TRIGGERED: UNKNOWN' (2026-10-16)",
    ),
    AlgoStatusEntry(
        status="FINISHED",
        klass=AlgoStatusClass.UNKNOWN,
        meaning=(
            "The triggered conditional order has been filled or canceled in the matching engine."
        ),
        source_note=f"{_RECORD} line 'class FINISHED: UNKNOWN' (2026-10-16)",
    ),
    AlgoStatusEntry(
        status="CANCELED",
        klass=AlgoStatusClass.UNKNOWN,
        meaning="The conditional order has been canceled.",
        source_note=f"{_RECORD} line 'class CANCELED: UNKNOWN' (2026-10-16)",
    ),
    AlgoStatusEntry(
        status="REJECTED",
        klass=AlgoStatusClass.TERMINAL_FAILED,
        meaning=(
            "The conditional order has been denied by the matching engine, such as in "
            "scenarios of margin check failures."
        ),
        source_note=(
            f"{_DOCUMENTED}; the record's default (REJECTED is TERMINAL_FAILED), {_RECORD}"
        ),
    ),
    AlgoStatusEntry(
        status="EXPIRED",
        klass=AlgoStatusClass.TERMINAL_FAILED,
        meaning=(
            "The conditional order was canceled by the system (a GTE_GTC example; the "
            "tool's paraphrase, not a quotation)."
        ),
        source_note=(
            f"{_DOCUMENTED}; the record's default (EXPIRED is TERMINAL_FAILED), {_RECORD}"
        ),
    ),
)

ALGO_STATUS_TABLE: Mapping[str, AlgoStatusEntry] = MappingProxyType(
    {entry.status: entry for entry in _ENTRIES}
)

if frozenset(ALGO_STATUS_TABLE) != ALGO_STATUS_VOCABULARY or len(_ENTRIES) != len(
    ALGO_STATUS_TABLE
):
    raise RuntimeError("ALGO_STATUS_TABLE must cover exactly ALGO_STATUS_VOCABULARY once")


def classify_algo_status(value: object) -> AlgoStatusClass:
    """Return the class of an algo-order status; UNKNOWN for anything unseen.

    Only an exact (case-sensitive) vocabulary string is looked up; None, the
    empty string, another case, surrounding whitespace, bytes and any other
    non-string value are UNKNOWN (fail closed, never ACTIVE).
    """
    if not isinstance(value, str):
        return AlgoStatusClass.UNKNOWN
    entry = ALGO_STATUS_TABLE.get(value)
    if entry is None:
        return AlgoStatusClass.UNKNOWN
    return entry.klass


def is_protection_confirmed(value: object) -> bool:
    """True if and only if the status's class is ACTIVE (a resting, untriggered stop)."""
    return classify_algo_status(value) is AlgoStatusClass.ACTIVE


__all__ = [
    "ALGO_STATUS_TABLE",
    "ALGO_STATUS_VOCABULARY",
    "AlgoStatusClass",
    "AlgoStatusEntry",
    "classify_algo_status",
    "is_known_algo_status",
    "is_protection_confirmed",
]
