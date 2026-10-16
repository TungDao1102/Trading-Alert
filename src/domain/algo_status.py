"""Documented vocabulary of the Binance algo-order status (Phase 18, plan 18-03).

This file holds only the documented vocabulary of the `X` field of the
user-data `ALGO_UPDATE` event: the seven values listed on the Binance
"Algo Order Update" section (read 2026-10-16 as a WebFetch summary, not
character-exact and not verified live; docs/SOURCES.md "Facts read for
Phase 18"). The classification table (which status counts as active,
terminal or unknown, CONTEXT D-07) is added by plan 18-06, not here.

Pure: standard library only, no wall clock, no float. A status outside this
set is never coerced: the stream parser turns it into an UNKNOWN_ALGO_STATUS
anomaly (fail closed, D-05). Whether the REST `algoStatus` vocabulary equals
this set is UNVERIFIED (research F3; a probe capture).
"""

from __future__ import annotations

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


__all__ = ["ALGO_STATUS_VOCABULARY", "is_known_algo_status"]
