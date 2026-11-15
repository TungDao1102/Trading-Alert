"""Post-cancel verification: a cancel is not done until Binance shows it (Phase 20, D-17, F-502).

The adapter's cancel methods return `None` both for a real cancel and for Binance's -2011
("unknown order") answer (research Pitfall 5). For an ENTRY the absent answer can mean the order
FILLED, so a returned cancel proves nothing. These helpers ask Binance once more, by the
deterministic client id, and turn the answer into a `CancelVerdict`:

- `CANCELED`: the order exists and its status is CANCELED. Only this verdict is a cancel.
- `FILLED_OR_PARTIAL`: an entry that is FILLED or PARTIALLY_FILLED. It is never "canceled" and the
  caller must treat the exposure as real (the protection coordinator owns it).
- `STILL_OPEN`: the order still rests (NEW). The cancel did not take effect.
- `GONE_NOT_CANCELED`: the order is terminal or triggered for another reason (an entry EXPIRED, an
  algo TRIGGERING / TRIGGERED / FINISHED / REJECTED / EXPIRED), or an algo order no longer answers
  to its id. It no longer rests, but nothing proves the cancel did it.
- `UNKNOWN`: the query failed, answered "not found" for an entry (absent right after a cancel is
  not proof: the 3-day lookup window, an id freed by a fill), or returned a status outside the
  known set. Fail closed: never treated as a cancel.

The query never raises (an `Exception` becomes `UNKNOWN`; `CancelledError` and other
`BaseException` pass through). Only the exception CLASS NAME is kept, in `CancelDetail.error_type`,
because an SDK network error embeds the request URL with its signature and the journal is
append-only. Order and algo statuses are Binance's own words and safe to journal.

About the algo status CANCELED: `src/domain/algo_status.py` classes it UNKNOWN (owner record
18-DEC-O-18-01) because that class decides whether a stop is a CONFIRMED PROTECTION. Here the same
string is used for the opposite question, "did this leg stop resting because we canceled it", and
only the exact vocabulary string CANCELED answers yes. No new status string is introduced.

Pure: standard library plus `src.domain`; no wall clock, no float, no SDK, no placement call.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.domain.algo_status import AlgoStatusClass, classify_algo_status, is_known_algo_status


class CancelVerdict(str, Enum):
    """What a query after a cancel showed (D-17)."""

    CANCELED = "CANCELED"
    FILLED_OR_PARTIAL = "FILLED_OR_PARTIAL"
    STILL_OPEN = "STILL_OPEN"
    GONE_NOT_CANCELED = "GONE_NOT_CANCELED"
    UNKNOWN = "UNKNOWN"


@dataclass
class CancelDetail:
    """Optional out-parameter: what the post-cancel query returned, for the audit record.

    `observed_status` is Binance's own status string (None when nothing usable came back);
    `error_type` is the exception class name when the query raised. Never message text.
    """

    observed_status: str | None = None
    error_type: str | None = None


_ENTRY_CANCELED = "CANCELED"
_ENTRY_FILLED_OR_PARTIAL: frozenset[str] = frozenset({"FILLED", "PARTIALLY_FILLED"})
_ENTRY_GONE: frozenset[str] = frozenset({"EXPIRED", "EXPIRED_IN_MATCH"})
_ENTRY_OPEN = "NEW"

_ALGO_CANCELED = "CANCELED"
# TRIGGERING, TRIGGERED and FINISHED are class UNKNOWN in the domain table (they never confirm a
# protection); for a cancel they mean one thing: the leg left the resting book by itself.
_ALGO_TRIGGERED_OR_FINISHED: frozenset[str] = frozenset({"TRIGGERING", "TRIGGERED", "FINISHED"})


def _status_text(value: object) -> str | None:
    return value if isinstance(value, str) else None


async def confirm_entry_cancel(
    adapter: Any,
    *,
    symbol: str,
    client_order_id: str,
    detail: CancelDetail | None = None,
) -> CancelVerdict:
    """Query the entry by client id after a cancel and classify the answer (D-17, F-502).

    `found` must be exactly `True`; "not found" right after a cancel is `UNKNOWN`, never proof.
    """
    try:
        probe = await adapter.query_order_by_client(
            symbol=symbol, orig_client_order_id=client_order_id
        )
    except Exception as exc:  # noqa: BLE001 - any failure of the query is UNKNOWN, class name kept
        if detail is not None:
            detail.error_type = type(exc).__name__
        return CancelVerdict.UNKNOWN
    status = _status_text(getattr(probe, "status", None))
    if detail is not None:
        detail.observed_status = status
    if getattr(probe, "found", None) is not True:
        return CancelVerdict.UNKNOWN
    if status == _ENTRY_CANCELED:
        return CancelVerdict.CANCELED
    if status in _ENTRY_FILLED_OR_PARTIAL:
        return CancelVerdict.FILLED_OR_PARTIAL
    if status in _ENTRY_GONE:
        return CancelVerdict.GONE_NOT_CANCELED
    if status == _ENTRY_OPEN:
        return CancelVerdict.STILL_OPEN
    return CancelVerdict.UNKNOWN


async def confirm_algo_cancel(
    adapter: Any,
    *,
    client_algo_id: str,
    detail: CancelDetail | None = None,
) -> CancelVerdict:
    """Query the algo order by client id after a cancel and classify the answer (D-17).

    A clean "not found" (`found` exactly `False`) means no algo order answers to the id: it is
    `GONE_NOT_CANCELED`. Unlike an entry, an absent algo order cannot hide exposure, but the
    absence is not proof that the cancel removed it (it may never have existed, or have been
    triggered); callers that need the difference read the verdict.
    """
    try:
        probe = await adapter.query_algo_order_by_client(client_algo_id=client_algo_id)
    except Exception as exc:  # noqa: BLE001 - any failure of the query is UNKNOWN, class name kept
        if detail is not None:
            detail.error_type = type(exc).__name__
        return CancelVerdict.UNKNOWN
    found = getattr(probe, "found", None)
    status = _status_text(getattr(probe, "algo_status", None))
    if detail is not None:
        detail.observed_status = status
    if found is False:
        return CancelVerdict.GONE_NOT_CANCELED
    if found is not True:
        return CancelVerdict.UNKNOWN
    if status == _ALGO_CANCELED:
        return CancelVerdict.CANCELED
    if status in _ALGO_TRIGGERED_OR_FINISHED:
        return CancelVerdict.GONE_NOT_CANCELED
    if not is_known_algo_status(status):
        return CancelVerdict.UNKNOWN
    klass = classify_algo_status(status)
    if klass is AlgoStatusClass.ACTIVE:
        return CancelVerdict.STILL_OPEN
    if klass is AlgoStatusClass.TERMINAL_FAILED:  # REJECTED, EXPIRED: no longer resting
        return CancelVerdict.GONE_NOT_CANCELED
    return CancelVerdict.UNKNOWN


# A verdict after which the order no longer rests on the exchange (used by the manual close and
# the sweeper to decide that a leg is "proven gone"). Never includes UNKNOWN or STILL_OPEN.
PROVEN_GONE: frozenset[CancelVerdict] = frozenset(
    {CancelVerdict.CANCELED, CancelVerdict.GONE_NOT_CANCELED}
)


__all__ = [
    "PROVEN_GONE",
    "CancelDetail",
    "CancelVerdict",
    "confirm_algo_cancel",
    "confirm_entry_cancel",
]
