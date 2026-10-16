"""Exchange error taxonomy: one category per (HTTP class, Binance code, call kind).

Classification uses the triple (SDK error class, int Binance code, call kind)
and nothing else (CONTEXT D-09, D-10; research F4, Pattern 3, P10). Nothing in
this module parses or receives exception message text: the SDK normalizer in
`src/adapters/binance_errors.py` passes only the class, the int body code and
the Retry-After seconds.

The code table is documentation text read per docs/SOURCES.md section "Facts
read for Phase 18" (WebFetch summaries, not character-exact and not verified
live). A code seen only on the Demo host carries the evidence label
`demo-observed` and is never described as documented.

A code or class that is not in the table is UNKNOWN_EXCHANGE_ERROR: ambiguous,
never "absent", never retried, SAFE_MODE-eligible (D-10).

Pure: standard library only, no wall clock, no float, no randomness.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType


class HttpClass(StrEnum):
    """Which SDK error class (or none) carried the failure.

    The SDK raises one class per HTTP status group; its `status_code` attribute
    is the Binance body code for 400, 401, 403, 404, 418 and 429, the HTTP
    status for 5xx, and None for any other 4xx (research F4).
    """

    BAD_REQUEST = "BAD_REQUEST"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    BANNED_418 = "BANNED_418"
    TOO_MANY_429 = "TOO_MANY_429"
    SERVER_5XX = "SERVER_5XX"
    CLIENT_OTHER = "CLIENT_OTHER"
    NETWORK = "NETWORK"
    NON_SDK = "NON_SDK"


class CallKind(StrEnum):
    """What the failing call was doing; the same code means different things per kind."""

    PLACEMENT = "PLACEMENT"
    CANCEL = "CANCEL"
    QUERY = "QUERY"
    LISTEN_KEY = "LISTEN_KEY"
    TIME = "TIME"


class ExchangeErrorCategory(StrEnum):
    ORDER_ABSENT = "ORDER_ABSENT"
    DUPLICATE_CLIENT_ID = "DUPLICATE_CLIENT_ID"
    REJECTED_DEFINITIVE = "REJECTED_DEFINITIVE"
    PRECONDITION_NO_POSITION = "PRECONDITION_NO_POSITION"
    CLOCK_SKEW = "CLOCK_SKEW"
    AUTH_OR_SIGNATURE = "AUTH_OR_SIGNATURE"
    RATE_LIMITED = "RATE_LIMITED"
    IP_BANNED = "IP_BANNED"
    STATUS_UNKNOWN = "STATUS_UNKNOWN"
    INVALID_LISTEN_KEY = "INVALID_LISTEN_KEY"
    POSITION_MODE = "POSITION_MODE"
    UNKNOWN_EXCHANGE_ERROR = "UNKNOWN_EXCHANGE_ERROR"


def _is_strict_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True, slots=True)
class ErrorFacts:
    """The only facts classification may use: class, int body code, Retry-After seconds."""

    http_class: HttpClass
    code: int | None
    retry_after_seconds: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.http_class, HttpClass):
            raise TypeError("http_class must be an HttpClass")
        if self.code is not None and not _is_strict_int(self.code):
            raise TypeError("code must be an int (not a bool) or None")
        if self.retry_after_seconds is not None and (
            not _is_strict_int(self.retry_after_seconds) or self.retry_after_seconds < 0
        ):
            raise ValueError("retry_after_seconds must be a non-negative int (not a bool) or None")


@dataclass(frozen=True, slots=True)
class CodeEntry:
    """One documented (or Demo-observed) Binance error code and its category per call kind.

    A call kind missing from `categories_by_call_kind` classifies as
    UNKNOWN_EXCHANGE_ERROR: the code was not expected on that kind of call.
    """

    code: int
    name: str
    categories_by_call_kind: Mapping[CallKind, ExchangeErrorCategory]
    source: str
    read_date: str
    evidence: str
    note: str


ERROR_TABLE_SOURCE: str = "docs/SOURCES.md, Facts read for Phase 18, error-code row"
ERROR_TABLE_READ_DATE: str = "2026-10-16"

_ABSENT_ON_QUERY_AND_CANCEL: Mapping[CallKind, ExchangeErrorCategory] = MappingProxyType(
    {
        CallKind.QUERY: ExchangeErrorCategory.ORDER_ABSENT,
        CallKind.CANCEL: ExchangeErrorCategory.ORDER_ABSENT,
    }
)


def _entry(
    code: int,
    name: str,
    categories: Mapping[CallKind, ExchangeErrorCategory],
    evidence: str,
    note: str,
) -> CodeEntry:
    return CodeEntry(
        code=code,
        name=name,
        categories_by_call_kind=MappingProxyType(dict(categories)),
        source=ERROR_TABLE_SOURCE,
        read_date=ERROR_TABLE_READ_DATE,
        evidence=evidence,
        note=note,
    )


ERROR_CODE_TABLE: Mapping[int, CodeEntry] = MappingProxyType(
    {
        entry.code: entry
        for entry in (
            _entry(
                -2011,
                "CANCEL_REJECTED",
                _ABSENT_ON_QUERY_AND_CANCEL,
                "documented",
                "Error-code page, re-read 2026-10-16: 'Unknown order sent'.",
            ),
            _entry(
                -2013,
                "NO_SUCH_ORDER",
                _ABSENT_ON_QUERY_AND_CANCEL,
                "documented",
                "Error-code page, re-read 2026-10-16: 'Order does not exist.'; also "
                "Demo-observed for GET /fapi/v1/algoOrder (09-DEMO-REHEARSAL-FINDINGS "
                "finding 1).",
            ),
        )
    }
)

_TABLE_CLASSES: frozenset[HttpClass] = frozenset({HttpClass.BAD_REQUEST, HttpClass.NOT_FOUND})


def classify(facts: ErrorFacts, call_kind: CallKind) -> ExchangeErrorCategory:
    """The category of one failure, from (class, code, call kind) only."""
    if not isinstance(facts, ErrorFacts):
        raise TypeError("facts must be ErrorFacts")
    if not isinstance(call_kind, CallKind):
        raise TypeError("call_kind must be a CallKind")
    if facts.http_class in _TABLE_CLASSES and facts.code is not None:
        entry = ERROR_CODE_TABLE.get(facts.code)
        if entry is not None:
            return entry.categories_by_call_kind.get(
                call_kind, ExchangeErrorCategory.UNKNOWN_EXCHANGE_ERROR
            )
    return ExchangeErrorCategory.UNKNOWN_EXCHANGE_ERROR


__all__ = [
    "ERROR_CODE_TABLE",
    "ERROR_TABLE_READ_DATE",
    "ERROR_TABLE_SOURCE",
    "CallKind",
    "CodeEntry",
    "ErrorFacts",
    "ExchangeErrorCategory",
    "HttpClass",
    "classify",
]
