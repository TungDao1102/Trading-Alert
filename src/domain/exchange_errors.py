"""Exchange error taxonomy: one category per (HTTP class, Binance code, call kind).

Classification uses the triple (SDK error class, int Binance code, call kind)
and nothing else (CONTEXT D-09, D-10; research F4, Pattern 3, P10). Nothing in
this module parses or receives exception message text: the SDK normalizer in
`src/adapters/binance_errors.py` passes only the class, the int body code and
the Retry-After seconds.

The code table is documentation text read per docs/SOURCES.md section "Facts
read for Phase 18" (WebFetch summaries, not character-exact and not verified
live), read on 2026-10-16 and, for -1106, -4016, -4024 and -1125, read again on
2026-10-17. A code seen only on the Demo host carries the evidence label
`demo-observed` and is never described as documented; a documented code that the
Demo also answered keeps `documented` and carries the Demo date separately.

A code or class that is not in the table is UNKNOWN_EXCHANGE_ERROR: ambiguous,
never "absent", never retried, SAFE_MODE-eligible (D-10).

Retry and rate-limit rules follow the user's record
`.planning/phases/18-user-data-stream-error-taxonomy/decisions/18-DEC-O-18-01.md`
and its amendment of 2026-10-16: no call is retried automatically because of a
418 or a 429; retry is allowed only for status-unknown failures of read,
cancel, time and listenKey calls; a placement is never retried. The 418 and
429 fallback waits and the cap are required arguments: no wait number exists in
this module.

Pure: standard library only, no wall clock, no float, no randomness.
"""

from __future__ import annotations

import re
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
    # -1008: system-level overload protection of the node (quick task 261020-g1a). Not a
    # request-rate limit: never recorded in the REST gate, never retried automatically.
    SYSTEM_THROTTLED = "SYSTEM_THROTTLED"
    STATUS_UNKNOWN = "STATUS_UNKNOWN"
    INVALID_LISTEN_KEY = "INVALID_LISTEN_KEY"
    POSITION_MODE = "POSITION_MODE"
    UNKNOWN_EXCHANGE_ERROR = "UNKNOWN_EXCHANGE_ERROR"


_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
# The Demo probe run whose answers label the codes below (second run 2026-10-16T17:36:12Z;
# the first run of the same day answered the same codes). Demo evidence, not mainnet.
DEMO_PROBE_DATE = "2026-10-16"
# The Demo user-data smoke run (20261016T140446Z) that answered -1125 on a keepalive after a
# delete (evidence/18-smoke-check.txt item f). Demo evidence, not mainnet.
DEMO_SMOKE_DATE = "2026-10-16"
# The Phase 19 Demo probe run 20261022T120055Z (case gtd_min_lifetime_boundary) that answered
# -5040 on a GTD entry (plan 20-27). Demo evidence, not mainnet.
DEMO_GTD_PROBE_DATE = "2026-10-22"


def _is_strict_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class PreSendRefusal(Exception):  # noqa: N818 - a refusal, not an error of the caller
    """Raised before anything was sent: the exchange never received the request (D-21).

    A subclass means "nothing reached the exchange" (a REST gate pause or ban, a clock-drift
    entry block, a missing signed-call policy). It is never an ambiguous send, so the
    execution core can retry or fall back without treating it as a possible placement. An
    exception that is not a `PreSendRefusal` carries no such guarantee.
    """


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


# documented: on the Binance error-code page (the 2026-10-16 re-read, the 2026-10-17 re-read
# of four codes, or the research baseline B7 of 2026-10-15); demo-observed: seen only on the Demo
# host, absent from the page; documented-elsewhere: recorded in another
# docs/SOURCES.md row, not on the Phase 18 error-code reads.
EVIDENCE_LABELS: frozenset[str] = frozenset({"documented", "demo-observed", "documented-elsewhere"})


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
    # ISO date of the documentation read this entry rests on (ERROR_TABLE_READ_DATE unless a
    # later read of the page is recorded for the entry).
    read_date: str
    evidence: str
    note: str
    # ISO date of a Demo observation of this code (evidence/18-probe-check.txt), or None.
    # Additive to `evidence`: a documented code that the Demo probe also answered stays
    # "documented" (its page reading is unchanged) and carries the Demo date here;
    # `read_date` is the documentation read date and is never changed by an observation.
    demo_observed_on: str | None = None

    def __post_init__(self) -> None:
        if self.evidence not in EVIDENCE_LABELS:
            raise ValueError(f"unknown evidence label: {self.evidence!r}")
        if not _ISO_DATE.fullmatch(self.read_date):
            raise ValueError("read_date must be an ISO date (YYYY-MM-DD)")
        if self.demo_observed_on is not None and not _ISO_DATE.fullmatch(self.demo_observed_on):
            raise ValueError("demo_observed_on must be an ISO date (YYYY-MM-DD) or None")


ERROR_TABLE_SOURCE: str = "docs/SOURCES.md, Facts read for Phase 18, error-code row"
ERROR_TABLE_READ_DATE: str = "2026-10-16"
# The second read of the error-code page (plan 18-26): -1106, -4016, -4024 and -1125 only.
ERROR_TABLE_REREAD_DATE: str = "2026-10-17"
# The Phase 22 read of the error-code page through the llms-full bundle (22-RESEARCH.md,
# 2026-10-23): the nine margin-type and leverage codes only. The 2026-10-16 and 2026-10-17 reads
# are not claimed for them; no existing entry's read date or source changes.
ERROR_TABLE_PHASE22_READ_DATE: str = "2026-10-23"
ERROR_TABLE_PHASE22_SOURCE: str = "docs/SOURCES.md, Facts read for Phase 22, error-code row"

_C = ExchangeErrorCategory
_K = CallKind

_REREAD = "Error-code page, re-read 2026-10-16"
_REREAD_2 = "Error-code page, re-read 2026-10-17"
_BASELINE = (
    "Error-code page per research baseline B7 (WebFetch 2026-10-15, 18-RESEARCH.md F4); "
    "not quoted in the 2026-10-16 re-read summary, which found no difference for the "
    "codes it listed"
)


def _every(category: ExchangeErrorCategory) -> dict[CallKind, ExchangeErrorCategory]:
    return dict.fromkeys(CallKind, category)


def _on(category: ExchangeErrorCategory, *kinds: CallKind) -> dict[CallKind, ExchangeErrorCategory]:
    return dict.fromkeys(kinds, category)


def _entry(
    code: int,
    name: str,
    categories: Mapping[CallKind, ExchangeErrorCategory],
    evidence: str,
    note: str,
    demo_observed_on: str | None = None,
    *,
    read_date: str = ERROR_TABLE_READ_DATE,
    source: str = ERROR_TABLE_SOURCE,
) -> CodeEntry:
    return CodeEntry(
        code=code,
        name=name,
        categories_by_call_kind=MappingProxyType(dict(categories)),
        source=source,
        read_date=read_date,
        evidence=evidence,
        note=note,
        demo_observed_on=demo_observed_on,
    )


_REJECT_ON_PLACEMENT = _on(_C.REJECTED_DEFINITIVE, _K.PLACEMENT)
_ABSENT_ON_QUERY_AND_CANCEL = _on(_C.ORDER_ABSENT, _K.QUERY, _K.CANCEL)

ERROR_CODE_TABLE: Mapping[int, CodeEntry] = MappingProxyType(
    {
        entry.code: entry
        for entry in (
            # Rate limits. The SDK reports a 418 and a 429 by class; the class
            # rule in `classify` decides those, the code decides only a 400.
            _entry(
                -1003,
                "TOO_MANY_REQUESTS",
                _every(_C.RATE_LIMITED),
                "documented",
                f"{_REREAD}: the same code for the throttle and the IP-ban texts, so the "
                "SDK class (418 or 429) is what separates them.",
            ),
            _entry(
                -1008,
                "Request Throttled",
                _every(_C.SYSTEM_THROTTLED),
                "documented",
                f"{_BASELINE}. 'Request throttled by system-level protection.' Quick task "
                "261020-g1a read the error-code and general-info pages again on 2026-10-20 "
                "(WebFetch summaries, not character-exact): 'Request throttled by system-level "
                "protection. Reduce-only/close-position orders are exempt. Please try again.' "
                "and 'Server is currently overloaded with other requests. Please try again in a "
                "few minutes.'; general-info: the node has exceeded its maximum concurrency, "
                "rate-limit counting: not counted (overload protection), covered endpoints "
                "POST /fapi/v1/order and /batchOrders. So it is SYSTEM_THROTTLED, not "
                "RATE_LIMITED: it never pauses or bans the process-wide REST gate (a 429 or a "
                "418 class still does), and it is never retried automatically (a placement is "
                "never re-sent). General-info also names cancel orders as exempt; the error-code "
                "page does not, so nothing here relies on it.",
            ),
            _entry(
                -1015,
                "TOO_MANY_ORDERS",
                _every(_C.RATE_LIMITED),
                "documented",
                f"{_REREAD}: 'Too many new orders.'",
            ),
            # Execution status unknown.
            _entry(
                -1006,
                "UNEXPECTED_RESP",
                _every(_C.STATUS_UNKNOWN),
                "documented",
                f"{_BASELINE}. '... Execution status unknown.'",
            ),
            _entry(
                -1007,
                "TIMEOUT",
                _every(_C.STATUS_UNKNOWN),
                "documented",
                f"{_BASELINE}. 'Send status unknown; execution status unknown.'",
            ),
            # Clock and authentication.
            _entry(
                -1021,
                "INVALID_TIMESTAMP",
                _every(_C.CLOCK_SKEW),
                "documented",
                f"{_REREAD}: outside the recvWindow, or 1000ms ahead of the server's time. "
                "A drift re-measure, never an order retry.",
            ),
            _entry(
                -1022,
                "INVALID_SIGNATURE",
                _every(_C.AUTH_OR_SIGNATURE),
                "documented",
                f"{_REREAD}: 'Signature for this request is not valid.'",
            ),
            _entry(
                -2014,
                "BAD_API_KEY_FMT",
                _every(_C.AUTH_OR_SIGNATURE),
                "documented",
                f"{_BASELINE}.",
            ),
            _entry(
                -2015,
                "REJECTED_MBX_KEY",
                _every(_C.AUTH_OR_SIGNATURE),
                "documented",
                f"{_BASELINE}. Invalid API-key, IP, or permissions for action.",
            ),
            _entry(
                -2017,
                "API_KEYS_LOCKED",
                _every(_C.AUTH_OR_SIGNATURE),
                "documented",
                f"{_BASELINE}.",
            ),
            # listenKey.
            _entry(
                -1125,
                "INVALID_LISTEN_KEY",
                _on(_C.INVALID_LISTEN_KEY, _K.LISTEN_KEY),
                "documented",
                f"{_REREAD}: 'This listenKey does not exist.' {_REREAD_2}: the text was seen "
                "again, unchanged. That a keepalive of an expired key answers -1125 was "
                "observed on Demo (smoke) on 2026-10-16: evidence/18-smoke-check.txt item f, "
                "PUT after DELETE answered BAD_REQUEST -1125 (INVALID_LISTEN_KEY). Demo only, "
                "not mainnet; the Demo observation is not a page statement.",
                DEMO_SMOKE_DATE,
                read_date=ERROR_TABLE_REREAD_DATE,
            ),
            # Absence: only a query or a cancel can learn that an order is not there.
            _entry(
                -2011,
                "CANCEL_REJECTED",
                _ABSENT_ON_QUERY_AND_CANCEL,
                "documented",
                f"{_REREAD}: 'CANCEL_REJECTED' / 'Unknown order sent'. Demo probe: DELETE order "
                "and DELETE algoOrder of an absent order answered -2011 'Unknown order sent.'",
                DEMO_PROBE_DATE,
            ),
            _entry(
                -2013,
                "NO_SUCH_ORDER",
                _ABSENT_ON_QUERY_AND_CANCEL,
                "documented",
                f"{_REREAD}: 'Order does not exist.'; also Demo-observed for GET "
                "/fapi/v1/algoOrder (09-DEMO-REHEARSAL-FINDINGS finding 1). Demo probe: GET "
                "order and GET algoOrder of an absent order answered -2013.",
                DEMO_PROBE_DATE,
            ),
            # Duplicate client id (placement only).
            _entry(
                -4116,
                "DUPLICATED_CLIENT_ORDER_ID",
                _on(_C.DUPLICATE_CLIENT_ID, _K.PLACEMENT),
                "documented",
                f"{_REREAD}: 'clientOrderId is duplicated'. The duplicate clientAlgoId code "
                "is not on the page; the Demo probe observed it as -4116 'ClientOrderId is "
                "duplicated.' while the first clientAlgoId was open (not observed for a "
                "normal order).",
                DEMO_PROBE_DATE,
            ),
            # Position mode.
            _entry(
                -4067,
                "Position side change with open orders",
                _every(_C.POSITION_MODE),
                "documented",
                f"{_REREAD}: 'Position side cannot be changed if there exists open orders.'",
            ),
            _entry(
                -4068,
                "Position side change with position",
                _every(_C.POSITION_MODE),
                "documented",
                f"{_REREAD}: 'Position side cannot be changed if there exists position.'",
            ),
            # Precondition: no open position (Demo-observed only).
            _entry(
                -4509,
                "GTE without open position (project label; no page name)",
                _on(_C.PRECONDITION_NO_POSITION, _K.PLACEMENT),
                "demo-observed",
                "Absent from the error-code page in the 2026-10-16 read and in baseline B7. "
                "Observed on the Demo host on 2026-10-05 for a closePosition STOP_MARKET algo "
                "order placed with no open position: 'Time in Force (TIF) GTE can only be used "
                "with open positions.' (09-DEMO-REHEARSAL-FINDINGS finding 2; D055 context). "
                "The Demo probe of 2026-10-16 observed the same answer for the close-position "
                "variant while flat.",
                DEMO_PROBE_DATE,
            ),
            # GTD lifetime floor (Demo-observed only, plan 20-27, owner approval 2026-10-23).
            _entry(
                -5040,
                "GTD_TIME_TOO_SOON (project label; no page name)",
                _REJECT_ON_PLACEMENT,
                "demo-observed",
                "Absent from the error-code page in the 2026-10-16 read. Observed on the Binance "
                "Demo host on 2026-10-22 by the Phase 19 Demo probe run 20261022T120055Z, case "
                "gtd_min_lifetime_boundary "
                "(.planning/phases/19-execution-plan-binding-price-check/evidence/"
                "demo-probe-EVIDENCE-20261022T120055Z.json): a GTD LIMIT entry whose goodTillDate "
                "was 599 s ahead of the server time was rejected with BAD_REQUEST -5040 'The "
                "goodTillDate timestamp must be greater than the current time plus 600 seconds "
                "and smaller than 253402300799000 (UTC 9999-12-31 23:59:59)'; the same entry with "
                "601 s was accepted (NEW) and cancelled. A definitive rejection of a placement: "
                "nothing was placed. No retry; the consumer must not resend the entry with a "
                "different goodTillDate (a placement is never re-sent, D080). Demo only, not "
                "mainnet.",
                DEMO_GTD_PROBE_DATE,
            ),
            # Definitive rejections of a placement: margin, balance, notional,
            # filters, would-trigger, reduce-only and conditional-order rules.
            # Owner decision of 2026-10-17 (plan 18-26, decisions/18-DEC-TAXONOMY-CODES.md).
            _entry(
                -1106,
                "PARAM_NOT_REQUIRED",
                _REJECT_ON_PLACEMENT,
                "documented",
                f"{_REREAD_2}: 'A parameter was sent when not required.' / \"Parameter '%s' sent "
                'when not required." (the official USD-M page is the source). Demo probe '
                "(case rejected_protective_variants, reduce-only together with close position, "
                "2026-10-16): answered -1106 \"Parameter 'reduceonly' sent when not required.\" "
                "- the Demo text is kept apart from the page text. PARAM_NOT_REQUIRED can come "
                "from a wrongly built request, including reduceOnly sent together with "
                "positionSide in hedge mode; it is not mapped to POSITION_MODE because the code "
                "alone does not prove a wrong position mode. nautilus_trader issue 4231 is a "
                "secondary technical reference for the hedge-mode case only, not a source of "
                "this table. No retry; a rejection is never evidence that an order is "
                "protected.",
                DEMO_PROBE_DATE,
                read_date=ERROR_TABLE_REREAD_DATE,
            ),
            _entry(
                -4016,
                "PRICE_HIGHTER_THAN_MULTIPLIER_UP",
                _REJECT_ON_PLACEMENT,
                "documented",
                f"{_REREAD_2}: 'Price is higher than mark price multiplier cap.' (the page "
                "spells HIGHTER). Demo probe (case id_reuse_after_filled, 2026-10-16): answered "
                '-4016 "Limit price can\'t be higher than 86305.10." - the Demo wording '
                "differs from the page wording; the code and the name agree, so the two texts "
                "are kept apart. The price was above the mark price multiplier cap. There is "
                "no retry; a rejection is never evidence that an order is protected. Note "
                "that refreshing the mark price and the filters after this code is the "
                "consumer's job (recorded as an "
                "open follow-up for Phase 19/20); this table does not refresh or reuse a "
                "price.",
                DEMO_PROBE_DATE,
                read_date=ERROR_TABLE_REREAD_DATE,
            ),
            _entry(
                -4024,
                "PRICE_LOWER_THAN_MULTIPLIER_DOWN",
                _REJECT_ON_PLACEMENT,
                "documented",
                f"{_REREAD_2}: 'Price is lower than mark price multiplier floor.' (price below "
                "the mark price multiplier floor). This code was not observed on Demo: no "
                "probe evidence, so no Demo date. There is no retry; a rejection is never "
                "evidence that an order is "
                "protected. The table must not assume a snapshot (mark price, filters) was "
                "refreshed: refreshing it is the consumer's job (open follow-up for "
                "Phase 19/20).",
                read_date=ERROR_TABLE_REREAD_DATE,
            ),
            _entry(
                -2019,
                "MARGIN_NOT_SUFFICIEN",
                _REJECT_ON_PLACEMENT,
                "documented",
                f"{_REREAD}: 'Margin is insufficient.' (the name is printed so on the page).",
            ),
            _entry(
                -2018,
                "BALANCE_NOT_SUFFICIENT",
                _REJECT_ON_PLACEMENT,
                "documented",
                f"{_BASELINE}. 'Balance is insufficient.'",
            ),
            _entry(
                -4164,
                "MIN_NOTIONAL",
                _REJECT_ON_PLACEMENT,
                "documented",
                f"{_REREAD}: notional below the minimum (unless reduce only).",
            ),
            _entry(
                -2010,
                "NEW_ORDER_REJECTED",
                _REJECT_ON_PLACEMENT,
                "documented",
                f"{_BASELINE}.",
            ),
            _entry(
                -1111,
                "BAD_PRECISION",
                _REJECT_ON_PLACEMENT,
                "documented",
                f"{_BASELINE}. Filter rejection.",
            ),
            _entry(
                -4003,
                "QTY_LESS_THAN_ZERO",
                _REJECT_ON_PLACEMENT,
                "documented",
                f"{_BASELINE}. Filter rejection.",
            ),
            _entry(
                -4004,
                "QTY_LESS_THAN_MIN_QTY",
                _REJECT_ON_PLACEMENT,
                "documented",
                f"{_BASELINE}. Filter rejection.",
            ),
            _entry(
                -4005,
                "QTY_GREATER_THAN_MAX_QTY",
                _REJECT_ON_PLACEMENT,
                "documented",
                f"{_BASELINE}. Filter rejection.",
            ),
            _entry(
                -4014,
                "Price tick (descriptive; the page name was not recorded)",
                _REJECT_ON_PLACEMENT,
                "documented",
                f"{_BASELINE}. Filter rejection.",
            ),
            _entry(
                -2021,
                "ORDER_WOULD_IMMEDIATELY_TRIGGER",
                _REJECT_ON_PLACEMENT,
                "documented",
                f"{_REREAD}: 'Order would immediately trigger.' Also named in the New Algo "
                "Order section for a TRAILING_STOP_MARKET activatePrice on the wrong side. "
                "Demo probe: a wrong-side trigger answered -2021 'Order would immediately "
                "trigger.'",
                DEMO_PROBE_DATE,
            ),
            _entry(
                -4142,
                "STRATEGY_INVALID_TRIGGER_PRICE",
                _REJECT_ON_PLACEMENT,
                "documented",
                f"{_BASELINE}. A take profit or stop order that would trigger immediately.",
            ),
            _entry(
                -2022,
                "REDUCE_ONLY_REJECT",
                _REJECT_ON_PLACEMENT,
                "documented",
                f"{_BASELINE}. 'ReduceOnly Order is rejected.' (D055 probe outcome).",
            ),
            _entry(
                -2024,
                "POSITION_NOT_SUFFICIENT",
                _REJECT_ON_PLACEMENT,
                "documented",
                f"{_BASELINE}. 'Position is not sufficient.' (D055 probe outcome).",
            ),
            _entry(
                -2026,
                "REDUCE_ONLY_ORDER_TYPE_NOT_SUPPORTED",
                _REJECT_ON_PLACEMENT,
                "documented",
                f"{_BASELINE}. (D055 probe outcome).",
            ),
            _entry(
                -4120,
                "STOP_ORDER_SWITCH_ALGO",
                _REJECT_ON_PLACEMENT,
                "documented",
                f"{_BASELINE}. A conditional type sent to the normal order endpoint.",
            ),
            _entry(
                -4137,
                "QUANTITY_EXISTS_WITH_CLOSE_POSITION",
                _REJECT_ON_PLACEMENT,
                "documented",
                f"{_BASELINE}.",
            ),
            _entry(
                -4138,
                "REDUCE_ONLY_MUST_BE_TRUE",
                _REJECT_ON_PLACEMENT,
                "documented",
                f"{_BASELINE}. Its text conflicts with the New Algo Order page "
                "(09-EXCHANGE-FACTS Fact 3).",
            ),
            _entry(
                -4400,
                "Quantitative rules (only reduceOnly allowed)",
                _REJECT_ON_PLACEMENT,
                "documented",
                f"{_BASELINE}. Account restriction.",
            ),
            _entry(
                -4401,
                "Large position (only reduceOnly allowed)",
                _REJECT_ON_PLACEMENT,
                "documented",
                f"{_BASELINE}. Account restriction.",
            ),
            _entry(
                -1121,
                "Invalid symbol.",
                _on(_C.REJECTED_DEFINITIVE, _K.PLACEMENT, _K.CANCEL, _K.QUERY),
                "documented-elsewhere",
                "Not on the Phase 18 error-code reads. Recorded in docs/SOURCES.md section "
                "'Facts verified for Phase 13', Kline-Candlestick-Data delisted-symbol row "
                "(production REST answered -1121 'Invalid symbol.' on 2026-09-30; a live "
                "probe, not a page read); INVALID_SYMBOL_CODE in src/adapters/binance_usdm.py.",
            ),
            # Phase 22 (plan 22-03): the definitive refusals of the margin-type and leverage
            # changes and the entry-time leverage limits. Error-code page read 2026-10-23 through
            # the llms-full bundle (22-RESEARCH.md); the HTTP class of these codes is not stated
            # on the page and was not observed on Demo, so only the 400 and 404 classes decide.
            _entry(
                -4046,
                "NO_NEED_TO_CHANGE_MARGIN_TYPE",
                _REJECT_ON_PLACEMENT,
                "documented",
                'Documented, error-code page read 2026-10-23 (22-RESEARCH.md): "No need to change '
                'margin type." Requesting the margin type the symbol already has is '
                "an error and not a no-op, so the configuration guard decides by the "
                "verification read and not by this answer. HTTP class not stated on "
                "the page and not observed on Demo.",
                read_date=ERROR_TABLE_PHASE22_READ_DATE,
                source=ERROR_TABLE_PHASE22_SOURCE,
            ),
            _entry(
                -4047,
                "THERE_EXISTS_OPEN_ORDERS",
                _REJECT_ON_PLACEMENT,
                "documented",
                'Documented, error-code page read 2026-10-23 (22-RESEARCH.md): "Margin type '
                'cannot be changed if there exists open orders." Whether a pending '
                "conditional (algo) order counts is not documented; the guard refuses "
                "on open algo orders itself.",
                read_date=ERROR_TABLE_PHASE22_READ_DATE,
                source=ERROR_TABLE_PHASE22_SOURCE,
            ),
            _entry(
                -4048,
                "THERE_EXISTS_QUANTITY",
                _REJECT_ON_PLACEMENT,
                "documented",
                'Documented, error-code page read 2026-10-23 (22-RESEARCH.md): "Margin type '
                'cannot be changed if there exists position."',
                read_date=ERROR_TABLE_PHASE22_READ_DATE,
                source=ERROR_TABLE_PHASE22_SOURCE,
            ),
            _entry(
                -4028,
                "INVALID_LEVERAGE",
                _REJECT_ON_PLACEMENT,
                "documented",
                'Documented, error-code page read 2026-10-23 (22-RESEARCH.md): "Invalid '
                'leverage", "Leverage %s is not valid", "Leverage %s already exist '
                'with %s". Which code a leverage above the symbol maximum returns '
                "(this or -4209) is not stated and not observed.",
                read_date=ERROR_TABLE_PHASE22_READ_DATE,
                source=ERROR_TABLE_PHASE22_SOURCE,
            ),
            _entry(
                -4161,
                "ISOLATED_LEVERAGE_REJECT_WITH_POSITION",
                _REJECT_ON_PLACEMENT,
                "documented",
                'Documented, error-code page read 2026-10-23 (22-RESEARCH.md): "Leverage '
                "reduction is not supported in Isolated Margin Mode with open "
                'positions".',
                read_date=ERROR_TABLE_PHASE22_READ_DATE,
                source=ERROR_TABLE_PHASE22_SOURCE,
            ),
            _entry(
                -4168,
                "JOINT_MARGIN_REJECT_WITH_ISOLATED",
                _REJECT_ON_PLACEMENT,
                "documented",
                'Documented, error-code page read 2026-10-23 (22-RESEARCH.md): "Unable to adjust '
                'to isolated-margin mode under the Multi-Assets mode."',
                read_date=ERROR_TABLE_PHASE22_READ_DATE,
                source=ERROR_TABLE_PHASE22_SOURCE,
            ),
            _entry(
                -4209,
                "ADJUST_LEVERAGE_SYMBOL_FAILED",
                _REJECT_ON_PLACEMENT,
                "documented",
                'Documented, error-code page read 2026-10-23 (22-RESEARCH.md): "The max leverage '
                'of Symbol is 20x" / "Leverage adjustment failed. Current symbol max '
                'leverage limit is %sx".',
                read_date=ERROR_TABLE_PHASE22_READ_DATE,
                source=ERROR_TABLE_PHASE22_SOURCE,
            ),
            _entry(
                -2027,
                "MAX_LEVERAGE_RATIO",
                _REJECT_ON_PLACEMENT,
                "documented",
                'Documented, error-code page read 2026-10-23 (22-RESEARCH.md): "Exceeded the '
                'maximum allowable position at current leverage." An entry-time '
                "rejection (order notional above the limit of the current leverage).",
                read_date=ERROR_TABLE_PHASE22_READ_DATE,
                source=ERROR_TABLE_PHASE22_SOURCE,
            ),
            _entry(
                -2028,
                "MIN_LEVERAGE_RATIO",
                _REJECT_ON_PLACEMENT,
                "documented",
                'Documented, error-code page read 2026-10-23 (22-RESEARCH.md): "Leverage is '
                'smaller than permitted: insufficient margin balance." An entry-time '
                "rejection.",
                read_date=ERROR_TABLE_PHASE22_READ_DATE,
                source=ERROR_TABLE_PHASE22_SOURCE,
            ),
        )
    }
)

# The classes whose `status_code` is a Binance code that the table decides.
_TABLE_CLASSES: frozenset[HttpClass] = frozenset({HttpClass.BAD_REQUEST, HttpClass.NOT_FOUND})

# Class rules: the class decides, whatever the code.
_CLASS_RULES: Mapping[HttpClass, ExchangeErrorCategory] = MappingProxyType(
    {
        HttpClass.BANNED_418: _C.IP_BANNED,
        HttpClass.TOO_MANY_429: _C.RATE_LIMITED,
        HttpClass.SERVER_5XX: _C.STATUS_UNKNOWN,
        HttpClass.CLIENT_OTHER: _C.STATUS_UNKNOWN,
        HttpClass.NETWORK: _C.STATUS_UNKNOWN,
        HttpClass.UNAUTHORIZED: _C.AUTH_OR_SIGNATURE,
        HttpClass.FORBIDDEN: _C.AUTH_OR_SIGNATURE,
        HttpClass.NON_SDK: _C.UNKNOWN_EXCHANGE_ERROR,
    }
)


def classify(facts: ErrorFacts, call_kind: CallKind) -> ExchangeErrorCategory:
    """The category of one failure, from (class, code, call kind) only.

    The class rules come first: 418 is IP_BANNED, 429 RATE_LIMITED, 5xx, other
    4xx (408) and network errors STATUS_UNKNOWN, 401 and 403 AUTH_OR_SIGNATURE,
    a non-SDK exception UNKNOWN_EXCHANGE_ERROR. A 400 or 404 is decided by the
    table; a missing code, a code not in the table or a code not expected on
    this call kind is UNKNOWN_EXCHANGE_ERROR (never ORDER_ABSENT).
    """
    if not isinstance(facts, ErrorFacts):
        raise TypeError("facts must be ErrorFacts")
    if not isinstance(call_kind, CallKind):
        raise TypeError("call_kind must be a CallKind")
    by_class = _CLASS_RULES.get(facts.http_class)
    if by_class is not None:
        return by_class
    if facts.http_class in _TABLE_CLASSES and facts.code is not None:
        entry = ERROR_CODE_TABLE.get(facts.code)
        if entry is not None:
            return entry.categories_by_call_kind.get(call_kind, _C.UNKNOWN_EXCHANGE_ERROR)
    return _C.UNKNOWN_EXCHANGE_ERROR


# Call kinds that may be retried, and only for STATUS_UNKNOWN (D-11 as refined
# by the user's amendment of 2026-10-16: no retry on a 418 or a 429).
_RETRYABLE_CALL_KINDS: frozenset[CallKind] = frozenset(
    {_K.QUERY, _K.CANCEL, _K.TIME, _K.LISTEN_KEY}
)


def retry_eligible(category: ExchangeErrorCategory, call_kind: CallKind) -> bool:
    """True only for a status-unknown failure of a query, cancel, time or listenKey call.

    A placement is never retried for any category; RATE_LIMITED, IP_BANNED and
    SYSTEM_THROTTLED (-1008) are never retried for any call kind; definitive,
    auth, clock-skew and unknown errors are never retried.
    """
    if not isinstance(category, ExchangeErrorCategory):
        raise TypeError("category must be an ExchangeErrorCategory")
    if not isinstance(call_kind, CallKind):
        raise TypeError("call_kind must be a CallKind")
    return category is _C.STATUS_UNKNOWN and call_kind in _RETRYABLE_CALL_KINDS


def safe_mode_eligible(category: ExchangeErrorCategory) -> bool:
    """True only for UNKNOWN_EXCHANGE_ERROR: an answer the table cannot explain (D-10)."""
    if not isinstance(category, ExchangeErrorCategory):
        raise TypeError("category must be an ExchangeErrorCategory")
    return category is _C.UNKNOWN_EXCHANGE_ERROR


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """What a 418 or 429 means for the caller: never a retry, and how long REST waits.

    It carries only `retry` and `wait_seconds`: the end of a wait proves
    nothing about an order's cancel, fill or protective stop and must not be
    able to mark one resolved (user record 18-DEC-O-18-01.md).
    """

    retry: bool
    wait_seconds: int | None


def _require_positive_int(name: str, value: object) -> None:
    if not _is_strict_int(value) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive int (not a bool)")


def rate_limit_decision(
    category: ExchangeErrorCategory,
    retry_after_seconds: int | None,
    *,
    no_retry_after_wait_418_seconds: int,
    no_retry_after_wait_429_seconds: int,
    retry_after_cap_seconds: int,
) -> RateLimitDecision:
    """The REST wait for a rate-limit category; `retry` is False in every case.

    IP_BANNED waits a valid Retry-After, otherwise the 418 fallback (the REST
    ban); RATE_LIMITED waits a valid Retry-After, otherwise the 429 fallback
    (the process-wide REST pause); the cap bounds both. Any other category,
    SYSTEM_THROTTLED (-1008) included, gives `RateLimitDecision(False, None)`.
    A missing or unparseable Retry-After arrives here as None. The three waits are required keyword
    arguments with no default: the numbers are the user's (configuration),
    never this module's. The call kind is not an argument because no call kind
    may retry a 418 or a 429.
    """
    if not isinstance(category, ExchangeErrorCategory):
        raise TypeError("category must be an ExchangeErrorCategory")
    _require_positive_int("no_retry_after_wait_418_seconds", no_retry_after_wait_418_seconds)
    _require_positive_int("no_retry_after_wait_429_seconds", no_retry_after_wait_429_seconds)
    _require_positive_int("retry_after_cap_seconds", retry_after_cap_seconds)
    if retry_after_seconds is not None and (
        not _is_strict_int(retry_after_seconds) or retry_after_seconds < 0
    ):
        raise ValueError("retry_after_seconds must be a non-negative int (not a bool) or None")
    if category is _C.IP_BANNED:
        fallback = no_retry_after_wait_418_seconds
    elif category is _C.RATE_LIMITED:
        fallback = no_retry_after_wait_429_seconds
    else:
        return RateLimitDecision(retry=False, wait_seconds=None)
    wanted = fallback if retry_after_seconds is None else retry_after_seconds
    return RateLimitDecision(retry=False, wait_seconds=min(wanted, retry_after_cap_seconds))


__all__ = [
    "ERROR_CODE_TABLE",
    "ERROR_TABLE_PHASE22_READ_DATE",
    "ERROR_TABLE_PHASE22_SOURCE",
    "ERROR_TABLE_READ_DATE",
    "ERROR_TABLE_REREAD_DATE",
    "ERROR_TABLE_SOURCE",
    "DEMO_PROBE_DATE",
    "DEMO_SMOKE_DATE",
    "EVIDENCE_LABELS",
    "CallKind",
    "CodeEntry",
    "ErrorFacts",
    "ExchangeErrorCategory",
    "HttpClass",
    "PreSendRefusal",
    "RateLimitDecision",
    "classify",
    "rate_limit_decision",
    "retry_eligible",
    "safe_mode_eligible",
]
