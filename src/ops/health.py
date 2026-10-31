"""Health-check probes (Phase 9, plan 09-04).

Per SECURITY_AND_OPERATIONS.md section 4: the operator must be able to
monitor market feed freshness, last closed candle time, WS connection
state, user-data stream state, REST error rate, reconciliation drift,
database writes, Telegram delivery, unprotected positions, and orphaned
orders. Each probe is a pure function of caller-supplied inputs plus
injected `now_utc` (never the wall clock) that returns a frozen
`HealthCheckResult` and journals exactly one `HEALTH_CHECK` JournalEvent.
`run_health_checks` aggregates the probe results: any FAIL blocks
enablement (fail-closed per D-04 precedent). A DEGRADED result is decided per runtime
mode (plan 24-22, DECISIONS D056): see `run_health_checks`.

The module is dependency-free: stdlib + `src/domain/journal.py` and `src/domain/enums.py` only.
No Binance SDK, no python-telegram-bot, no SQLAlchemy, no Pydantic, no
Polars. The Telegram delivery probe consumes a narrow Protocol-typed
notify surface (mirrors `src/adapters/telegram_notify.py:TelegramBot`
structurally) so this module never imports PTB directly.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

from src.domain.enums import RejectionReason
from src.domain.journal import JournalEvent, content_hash_event_id

# --------------------------------------------------------------------------- #
# Status vocabulary — the only three values a probe may report.
# --------------------------------------------------------------------------- #

STATUS_PASS: str = "PASS"
STATUS_FAIL: str = "FAIL"
STATUS_DEGRADED: str = "DEGRADED"

_STATUSES: frozenset[str] = frozenset({STATUS_PASS, STATUS_FAIL, STATUS_DEGRADED})


class HealthRuntimeMode(StrEnum):
    """The runtime mode a verdict is judged for (D056). There is no default and no TESTNET.

    The values equal those of `src.adapters.binance_client.Environment` (a `StrEnum` as well), so
    a caller may pass its `Environment` member; this module does not import the adapter layer.
    """

    DEMO = "DEMO"
    LIVE = "LIVE"


# --------------------------------------------------------------------------- #
# Canonical check-name vocabulary — one per SECURITY_AND_OPERATIONS section 4
# item, in the order the document lists them. Tuple order is part of the
# acceptance contract (mirrors the DRILL_NAMES precedent in
# `src/ops/drills.py`).
# --------------------------------------------------------------------------- #

CHECK_MARKET_FEED_FRESHNESS: str = "market_feed_freshness"
CHECK_LAST_CLOSED_CANDLE_TIME: str = "last_closed_candle_time"
CHECK_WS_CONNECTION_STATE: str = "ws_connection_state"
CHECK_USER_DATA_STREAM_STATE: str = "user_data_stream_state"
CHECK_REST_ERROR_RATE: str = "rest_error_rate"
CHECK_RECONCILIATION_DRIFT: str = "reconciliation_drift"
CHECK_DB_WRITES: str = "db_writes"
CHECK_TELEGRAM_DELIVERY: str = "telegram_delivery"
CHECK_UNPROTECTED_POSITIONS: str = "unprotected_positions"
CHECK_ORPHANED_ORDERS: str = "orphaned_orders"

ALL_CHECK_NAMES: tuple[str, ...] = (
    CHECK_MARKET_FEED_FRESHNESS,
    CHECK_LAST_CLOSED_CANDLE_TIME,
    CHECK_WS_CONNECTION_STATE,
    CHECK_USER_DATA_STREAM_STATE,
    CHECK_REST_ERROR_RATE,
    CHECK_RECONCILIATION_DRIFT,
    CHECK_DB_WRITES,
    CHECK_TELEGRAM_DELIVERY,
    CHECK_UNPROTECTED_POSITIONS,
    CHECK_ORPHANED_ORDERS,
)

_ZERO_TIMEDELTA = timedelta(0)

# Divergence-kind literals this module reads (duck-typed, never imported
# from `src/reconcile/compare.py` — health.py stays dependency-free per
# the module-purity contract).
_DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE: str = "ENTRY_WITHOUT_PROTECTIVE"
_DIVERGENCE_KIND_ORPHAN_PROTECTIVE: str = "ORPHAN_PROTECTIVE"


# --------------------------------------------------------------------------- #
# Protocol-typed surfaces — health.py never imports the journal layer's
# concrete implementation or the Binance/Telegram SDKs.
# --------------------------------------------------------------------------- #


class JournalLike(Protocol):
    """Anything that quacks like the project journal for health probes."""

    def record(self, event: Any) -> None: ...


class NotifierLike(Protocol):
    """Narrow structural surface for the Telegram delivery probe.

    Mirrors `src/adapters/telegram_notify.py:TelegramBot.send_message`
    structurally without importing python-telegram-bot. `reply_markup`
    is optional so the health probe can send a plain text ping with no
    keyboard.
    """

    async def send_message(self, *, chat_id: Any, text: str, reply_markup: Any = None) -> Any: ...


# --------------------------------------------------------------------------- #
# Frozen dataclasses — the public health-probe contract.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class HealthCheckResult:
    """The result of one health-check probe.

    `check_name` is one of the canonical `ALL_CHECK_NAMES` values.
    `status` is one of `STATUS_PASS` / `STATUS_FAIL` / `STATUS_DEGRADED`.
    `detail` is a short human-readable string (never a secret — callers
    must not pass API keys/tokens/signatures into this field).
    `observed_at_utc` is the caller-supplied `now_utc` (never the wall
    clock — repeat runs with the same inputs are byte-identical).
    """

    check_name: str
    status: str
    detail: str
    observed_at_utc: datetime

    def __post_init__(self) -> None:
        if self.check_name not in ALL_CHECK_NAMES:
            raise ValueError(
                f"HealthCheckResult: unknown check_name {self.check_name!r} "
                f"(known: {list(ALL_CHECK_NAMES)})"
            )
        if self.status not in _STATUSES:
            raise ValueError(
                f"HealthCheckResult: unknown status {self.status!r} (known: {sorted(_STATUSES)})"
            )
        if not isinstance(self.detail, str):
            raise TypeError(f"detail must be str, got {type(self.detail).__name__}")
        if self.observed_at_utc.tzinfo is None:
            raise ValueError("HealthCheckResult: observed_at_utc must be UTC-aware")
        if self.observed_at_utc.utcoffset() != _ZERO_TIMEDELTA:
            raise ValueError("HealthCheckResult: observed_at_utc must be UTC")


@dataclass(frozen=True)
class HealthVerdict:
    """Aggregate verdict over a full `run_health_checks(...)` call.

    `is_no_trade=True` iff any probe result reports `STATUS_FAIL`, or
    the probe set is incomplete / has duplicates (fail-closed: RED or
    unevaluated health blocks enablement, per D-04 precedent).
    `reason_code` is `"HEALTH_CHECK_FAILED"` on fail, `"OK"` on pass.
    `results` preserves the input order for audit-trail readability.

    A PASS verdict is structurally complete (09-REVIEW WR-08): it must
    carry exactly one result per `ALL_CHECK_NAMES` entry and no FAIL —
    so a hand-built or partial "OK" verdict cannot unlock enablement.

    D056 (plan 24-22): `mode` is the runtime mode the verdict was judged for (None only for the
    legacy call without a mode, which keeps the old rule that DEGRADED passes) and
    `demo_degraded_allowed` records that the explicit DEMO flag was given. An "OK" verdict that
    holds a DEGRADED result must be a legacy verdict or a DEMO verdict with the flag; a LIVE
    verdict with a DEGRADED result is never "OK", and the flag is only valid in DEMO.
    """

    is_no_trade: bool
    reason_code: str
    results: tuple[HealthCheckResult, ...]
    mode: HealthRuntimeMode | None = None
    demo_degraded_allowed: bool = False

    @property
    def degraded_names(self) -> tuple[str, ...]:
        """The check names that reported DEGRADED, in result order."""
        return tuple(r.check_name for r in self.results if r.status == STATUS_DEGRADED)

    def __post_init__(self) -> None:
        if self.mode is not None and not isinstance(self.mode, HealthRuntimeMode):
            raise ValueError("HealthVerdict: mode must be a HealthRuntimeMode or None")
        if not isinstance(self.demo_degraded_allowed, bool):
            raise TypeError("HealthVerdict: demo_degraded_allowed must be a bool")
        if self.demo_degraded_allowed and self.mode is not HealthRuntimeMode.DEMO:
            raise ValueError("HealthVerdict: demo_degraded_allowed is only valid in DEMO mode")
        if not isinstance(self.reason_code, str) or self.reason_code == "":
            raise ValueError("reason_code must be a non-empty string")
        if self.is_no_trade and self.reason_code != RejectionReason.HEALTH_CHECK_FAILED.value:
            raise ValueError(
                "HealthVerdict: is_no_trade=True requires reason_code='HEALTH_CHECK_FAILED'"
            )
        if not self.is_no_trade and self.reason_code != "OK":
            raise ValueError("HealthVerdict: is_no_trade=False requires reason_code='OK'")
        if not self.is_no_trade and not _is_complete_passing_set(self.results):
            raise ValueError(
                "HealthVerdict: a PASS verdict requires exactly one non-FAIL "
                "result per ALL_CHECK_NAMES entry"
            )
        if (
            not self.is_no_trade
            and self.degraded_names
            and not _degraded_is_allowed(self.mode, self.demo_degraded_allowed)
        ):
            raise ValueError(
                "HealthVerdict: an OK verdict cannot hold a DEGRADED result in this mode "
                f"(mode={self.mode}, demo_degraded_allowed={self.demo_degraded_allowed})"
            )


# --------------------------------------------------------------------------- #
# Internal helpers.
# --------------------------------------------------------------------------- #


def _is_complete_passing_set(results: Sequence[HealthCheckResult]) -> bool:
    """True iff every canonical check ran exactly once and none FAILED."""
    names = [r.check_name for r in results]
    return (
        len(names) == len(ALL_CHECK_NAMES)
        and set(names) == set(ALL_CHECK_NAMES)
        and all(r.status != STATUS_FAIL for r in results)
    )


def _degraded_is_allowed(mode: HealthRuntimeMode | None, demo_degraded_allowed: bool) -> bool:
    """D056: DEGRADED passes only for the legacy no-mode call or in DEMO with the explicit flag."""
    if mode is None:
        return True
    return mode is HealthRuntimeMode.DEMO and demo_degraded_allowed


def _require_utc_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != _ZERO_TIMEDELTA:
        raise ValueError(f"{field_name} must be UTC, got offset {value.utcoffset()}")


def _build_payload_json(
    check_name: str, status: str, detail: str, extra: Mapping[str, str | bool] | None = None
) -> str:
    """Compact JSON serialisation for HEALTH_CHECK journal payloads.

    Only `check_name`, `status`, and `detail` are written by the probes — no
    caller is permitted to route secret material through `detail`
    (T-9-15 mitigation: the log-scan test asserts zero secret
    substrings across every emitted payload). The live producer (plan 24-22) adds the mode and
    the diagnostic fields (Python version, application revision) through `extra`; without
    `extra` the bytes are those of the Phase 9 probes.
    """
    document: dict[str, str | bool] = {"check": check_name, "status": status, "detail": detail}
    if extra:
        for key, value in extra.items():
            if key in document:
                raise ValueError(f"health payload: extra key {key!r} collides with a base key")
            document[key] = value
    return json.dumps(document, separators=(",", ":"))


def _health_check_event(check_name: str, now_utc: datetime, payload_json: str) -> JournalEvent:
    return JournalEvent(
        # 09-REVIEW WR-09: content-hash id — two different results of the
        # same probe at the same injected `now_utc` never collide.
        journal_event_id=content_hash_event_id(
            prefix="health_check",
            event_type="HEALTH_CHECK",
            entity_id=check_name,
            occurred_at_utc=now_utc,
            payload_json=payload_json,
        ),
        occurred_at_utc=now_utc,
        event_type="HEALTH_CHECK",
        entity_type="HealthProbe",
        entity_id=check_name,
        correlation_id="execution_health",
        payload_json=payload_json,
    )


def health_check_event(
    result: HealthCheckResult, *, extra: Mapping[str, str | bool] | None = None
) -> JournalEvent:
    """The `HEALTH_CHECK` journal event of one probe result (plan 24-22, D-31).

    Without `extra` this is exactly the event the probe itself journals. With `extra` (strings
    and booleans only, e.g. `mode`, `python_version`, `app_revision`) the same event carries the
    extra keys after the base ones and gets its own content-hash id.
    """
    payload_json = _build_payload_json(result.check_name, result.status, result.detail, extra)
    return _health_check_event(result.check_name, result.observed_at_utc, payload_json)


def _record_health_check_event(
    *,
    journal: JournalLike,
    check_name: str,
    status: str,
    detail: str,
    now_utc: datetime,
) -> None:
    payload_json = _build_payload_json(check_name, status, detail)
    journal.record(_health_check_event(check_name, now_utc, payload_json))


def _build_result(
    *,
    journal: JournalLike,
    check_name: str,
    status: str,
    detail: str,
    now_utc: datetime,
) -> HealthCheckResult:
    _require_utc_aware(now_utc, "now_utc")
    _record_health_check_event(
        journal=journal,
        check_name=check_name,
        status=status,
        detail=detail,
        now_utc=now_utc,
    )
    return HealthCheckResult(
        check_name=check_name,
        status=status,
        detail=detail,
        observed_at_utc=now_utc,
    )


def _get_field(entry: Any, field_name: str) -> Any:
    """Read a field from either an object (attribute) or a dict (key).

    Mirrors the duck-typed lookup used throughout `src/reconcile/*` and
    `src/execution/fill_monitor.py` so probes can accept both
    dataclass-style divergence objects and dict-style test fixtures.
    """
    if isinstance(entry, dict):
        return entry.get(field_name)
    return getattr(entry, field_name, None)


# --------------------------------------------------------------------------- #
# Public entry points — one probe per SECURITY_AND_OPERATIONS section 4 item.
# --------------------------------------------------------------------------- #


def check_market_feed_freshness(
    *,
    last_market_event_at_utc: datetime | None,
    now_utc: datetime,
    staleness_threshold: timedelta,
    journal: JournalLike,
) -> HealthCheckResult:
    """FAIL when the market feed has no recent event within `staleness_threshold`."""
    if last_market_event_at_utc is None:
        return _build_result(
            journal=journal,
            check_name=CHECK_MARKET_FEED_FRESHNESS,
            status=STATUS_FAIL,
            detail="no market event observed",
            now_utc=now_utc,
        )
    age = now_utc - last_market_event_at_utc
    if age > staleness_threshold or age < _ZERO_TIMEDELTA:
        return _build_result(
            journal=journal,
            check_name=CHECK_MARKET_FEED_FRESHNESS,
            status=STATUS_FAIL,
            detail=f"market feed stale: age={age}",
            now_utc=now_utc,
        )
    return _build_result(
        journal=journal,
        check_name=CHECK_MARKET_FEED_FRESHNESS,
        status=STATUS_PASS,
        detail=f"market feed fresh: age={age}",
        now_utc=now_utc,
    )


def check_last_closed_candle_time(
    *,
    last_closed_candle_close_utc: datetime | None,
    now_utc: datetime,
    expected_cadence: timedelta,
    journal: JournalLike,
) -> HealthCheckResult:
    """FAIL when the last closed candle is older than `expected_cadence`."""
    if last_closed_candle_close_utc is None:
        return _build_result(
            journal=journal,
            check_name=CHECK_LAST_CLOSED_CANDLE_TIME,
            status=STATUS_FAIL,
            detail="no closed candle observed",
            now_utc=now_utc,
        )
    age = now_utc - last_closed_candle_close_utc
    if age > expected_cadence or age < _ZERO_TIMEDELTA:
        return _build_result(
            journal=journal,
            check_name=CHECK_LAST_CLOSED_CANDLE_TIME,
            status=STATUS_FAIL,
            detail=f"last closed candle stale: age={age}",
            now_utc=now_utc,
        )
    return _build_result(
        journal=journal,
        check_name=CHECK_LAST_CLOSED_CANDLE_TIME,
        status=STATUS_PASS,
        detail=f"last closed candle fresh: age={age}",
        now_utc=now_utc,
    )


def check_ws_connection_state(
    *,
    connected: bool,
    now_utc: datetime,
    journal: JournalLike,
) -> HealthCheckResult:
    """FAIL when the market-data WS connection is not connected."""
    status = STATUS_PASS if connected else STATUS_FAIL
    detail = "connected" if connected else "disconnected"
    return _build_result(
        journal=journal,
        check_name=CHECK_WS_CONNECTION_STATE,
        status=status,
        detail=detail,
        now_utc=now_utc,
    )


def check_user_data_stream_state(
    *,
    connected: bool,
    now_utc: datetime,
    journal: JournalLike,
) -> HealthCheckResult:
    """FAIL when the user-data stream is not connected."""
    status = STATUS_PASS if connected else STATUS_FAIL
    detail = "connected" if connected else "disconnected"
    return _build_result(
        journal=journal,
        check_name=CHECK_USER_DATA_STREAM_STATE,
        status=status,
        detail=detail,
        now_utc=now_utc,
    )


def check_rest_error_rate(
    *,
    error_count: int,
    total_count: int,
    max_error_rate: Decimal,
    now_utc: datetime,
    journal: JournalLike,
) -> HealthCheckResult:
    """FAIL when the REST error rate exceeds `max_error_rate`.

    `total_count == 0` (no requests observed in the window) is treated
    as PASS — there is no evidence of errors, and blocking on an empty
    window would be a false positive, not a fail-closed posture.

    `error_count > total_count` is an impossible observation (more errors
    than requests, so the counters are broken or mixed windows): it is a
    FAIL result, never a pass and never a rate above 1 (G2-035, IN-07).
    Negative counts keep raising ValueError (caller programming error).
    """
    if error_count < 0 or total_count < 0:
        raise ValueError("check_rest_error_rate: counts must be >= 0")
    if error_count > total_count:
        return _build_result(
            journal=journal,
            check_name=CHECK_REST_ERROR_RATE,
            status=STATUS_FAIL,
            detail="REST error count exceeds request count; counters are inconsistent",
            now_utc=now_utc,
        )
    if total_count == 0:
        return _build_result(
            journal=journal,
            check_name=CHECK_REST_ERROR_RATE,
            status=STATUS_PASS,
            detail="no REST requests observed in window",
            now_utc=now_utc,
        )
    rate = Decimal(error_count) / Decimal(total_count)
    if rate > max_error_rate:
        return _build_result(
            journal=journal,
            check_name=CHECK_REST_ERROR_RATE,
            status=STATUS_FAIL,
            detail=f"REST error rate {rate} exceeds max {max_error_rate}",
            now_utc=now_utc,
        )
    return _build_result(
        journal=journal,
        check_name=CHECK_REST_ERROR_RATE,
        status=STATUS_PASS,
        detail=f"REST error rate {rate} within max {max_error_rate}",
        now_utc=now_utc,
    )


def check_reconciliation_drift(
    *,
    positions_reconciled: bool,
    now_utc: datetime,
    journal: JournalLike,
) -> HealthCheckResult:
    """FAIL when the position set is not reconciled (uncertain account state)."""
    status = STATUS_PASS if positions_reconciled else STATUS_FAIL
    detail = "reconciled" if positions_reconciled else "unreconciled"
    return _build_result(
        journal=journal,
        check_name=CHECK_RECONCILIATION_DRIFT,
        status=status,
        detail=detail,
        now_utc=now_utc,
    )


def check_db_writes(
    *,
    last_db_write_at_utc: datetime | None,
    now_utc: datetime,
    staleness_threshold: timedelta,
    journal: JournalLike,
) -> HealthCheckResult:
    """FAIL when the database has not accepted a write within `staleness_threshold`."""
    if last_db_write_at_utc is None:
        return _build_result(
            journal=journal,
            check_name=CHECK_DB_WRITES,
            status=STATUS_FAIL,
            detail="no database write observed",
            now_utc=now_utc,
        )
    age = now_utc - last_db_write_at_utc
    if age > staleness_threshold or age < _ZERO_TIMEDELTA:
        return _build_result(
            journal=journal,
            check_name=CHECK_DB_WRITES,
            status=STATUS_FAIL,
            detail=f"database writes stale: age={age}",
            now_utc=now_utc,
        )
    return _build_result(
        journal=journal,
        check_name=CHECK_DB_WRITES,
        status=STATUS_PASS,
        detail=f"database writes fresh: age={age}",
        now_utc=now_utc,
    )


async def check_telegram_delivery(
    *,
    notifier: NotifierLike | None,
    chat_id: Any,
    probe_text: str,
    now_utc: datetime,
    journal: JournalLike,
) -> HealthCheckResult:
    """FAIL when the Telegram delivery probe cannot be sent or is rejected.

    Never logs `probe_text`, `chat_id`, or any exception payload that
    could carry bot-token/secret material — only the exception's type
    name is recorded (T-9-15).
    """
    if notifier is None:
        return _build_result(
            journal=journal,
            check_name=CHECK_TELEGRAM_DELIVERY,
            status=STATUS_FAIL,
            detail="no notifier configured",
            now_utc=now_utc,
        )
    try:
        response = await notifier.send_message(chat_id=chat_id, text=probe_text)
    except Exception as exc:  # noqa: BLE001 — fail-closed probe, never re-raise
        return _build_result(
            journal=journal,
            check_name=CHECK_TELEGRAM_DELIVERY,
            status=STATUS_FAIL,
            detail=f"send_message raised {type(exc).__name__}",
            now_utc=now_utc,
        )
    if response is None or response is False:
        return _build_result(
            journal=journal,
            check_name=CHECK_TELEGRAM_DELIVERY,
            status=STATUS_FAIL,
            detail="send_message returned no response",
            now_utc=now_utc,
        )
    return _build_result(
        journal=journal,
        check_name=CHECK_TELEGRAM_DELIVERY,
        status=STATUS_PASS,
        detail="probe delivered",
        now_utc=now_utc,
    )


def check_telegram_delivery_observed(
    *,
    last_delivery_ok: bool | None,
    now_utc: datetime,
    journal: JournalLike,
) -> HealthCheckResult:
    """FAIL when no Telegram delivery was observed yet, or the latest one failed (plan 24-22).

    `check_telegram_delivery` sends a message and would message the owner on every health tick.
    The live process instead reports the outcome of its latest real send (alert drain, startup
    probe): None means none was observed, which fails closed.
    """
    if last_delivery_ok is None:
        status, detail = STATUS_FAIL, "no telegram delivery observed"
    elif last_delivery_ok:
        status, detail = STATUS_PASS, "latest telegram delivery succeeded"
    else:
        status, detail = STATUS_FAIL, "latest telegram delivery failed"
    return _build_result(
        journal=journal,
        check_name=CHECK_TELEGRAM_DELIVERY,
        status=status,
        detail=detail,
        now_utc=now_utc,
    )


def check_not_applicable(
    *,
    check_name: str,
    detail: str,
    now_utc: datetime,
    journal: JournalLike,
) -> HealthCheckResult:
    """A DEGRADED result for a check that does not describe this process (plan 24-22, D056).

    The live process has no candle feed, so `last_closed_candle_time` is reported DEGRADED, not
    PASS (it is not true) and not FAIL (nothing is wrong). Whether DEGRADED may pass is the
    mode's decision in `run_health_checks`.
    """
    return _build_result(
        journal=journal,
        check_name=check_name,
        status=STATUS_DEGRADED,
        detail=detail,
        now_utc=now_utc,
    )


def check_unprotected_positions(
    *,
    divergences: Sequence[Any],
    now_utc: datetime,
    journal: JournalLike,
) -> HealthCheckResult:
    """FAIL when any divergence is ENTRY_WITHOUT_PROTECTIVE (T-9-14)."""
    unprotected_count = sum(
        1 for d in divergences if _get_field(d, "kind") == _DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE
    )
    if unprotected_count > 0:
        return _build_result(
            journal=journal,
            check_name=CHECK_UNPROTECTED_POSITIONS,
            status=STATUS_FAIL,
            detail=f"{unprotected_count} unprotected position(s)",
            now_utc=now_utc,
        )
    return _build_result(
        journal=journal,
        check_name=CHECK_UNPROTECTED_POSITIONS,
        status=STATUS_PASS,
        detail="no unprotected positions",
        now_utc=now_utc,
    )


def check_orphaned_orders(
    *,
    divergences: Sequence[Any],
    now_utc: datetime,
    journal: JournalLike,
) -> HealthCheckResult:
    """FAIL when any divergence is ORPHAN_PROTECTIVE (RUNBOOK section 4)."""
    orphan_count = sum(
        1 for d in divergences if _get_field(d, "kind") == _DIVERGENCE_KIND_ORPHAN_PROTECTIVE
    )
    if orphan_count > 0:
        return _build_result(
            journal=journal,
            check_name=CHECK_ORPHANED_ORDERS,
            status=STATUS_FAIL,
            detail=f"{orphan_count} orphaned order(s)",
            now_utc=now_utc,
        )
    return _build_result(
        journal=journal,
        check_name=CHECK_ORPHANED_ORDERS,
        status=STATUS_PASS,
        detail="no orphaned orders",
        now_utc=now_utc,
    )


# --------------------------------------------------------------------------- #
# Aggregate verdict.
# --------------------------------------------------------------------------- #


def run_health_checks(
    *,
    results: Sequence[HealthCheckResult],
    mode: HealthRuntimeMode | str | None = None,
    demo_degraded_allowed: bool = False,
) -> HealthVerdict:
    """Aggregate probe results: any FAIL or gap blocks enablement (fail-closed).

    The DEGRADED rows (D056, plan 24-22; a DEGRADED result means a check that does not describe
    the process or cannot be fully judged, and nothing may quietly treat it as healthy):

    ========  ==============================  ==========================================
    mode      `demo_degraded_allowed`         a DEGRADED result
    ========  ==============================  ==========================================
    LIVE      must be False (else ValueError)  the verdict is not OK: it cannot enable any
                                              order-capable capability
    DEMO      False                           the verdict is not OK
    DEMO      True (explicit flag)            the verdict may be OK; the flag is stored on
                                              the verdict so it is journaled with the state
    None      must be False (else ValueError)  LEGACY call without a mode (only
                                              `scripts/demo_rehearsal.py`, until plan 24-29):
                                              the old rule, DEGRADED passes. The verdict carries
                                              no mode, so the live process refuses to enable
                                              from it, and every `src` caller passes a mode.
    ========  ==============================  ==========================================

    Args:
        results: The probe results to aggregate. Order is preserved for
            audit-trail readability.
        mode: The runtime mode (`HealthRuntimeMode`, or an `Environment` member of the same
            value). There is no TESTNET row: any other value raises ValueError.
        demo_degraded_allowed: The explicit DEMO flag. It can never be set in LIVE.

    Returns:
        A `HealthVerdict` with `is_no_trade=True` and
        `reason_code="HEALTH_CHECK_FAILED"` when any result reports
        `STATUS_FAIL`, OR when the set is not exactly one result per
        `ALL_CHECK_NAMES` entry (a missing or duplicated probe means the
        health state was not fully evaluated — 09-REVIEW WR-08), OR when a result is
        DEGRADED and the mode row above does not allow it;
        otherwise `is_no_trade=False` and `reason_code="OK"`.

    Raises:
        ValueError: empty `results`, a mode that is not DEMO or LIVE, or the flag set outside DEMO.
        TypeError: `demo_degraded_allowed` is not a bool.
    """
    if len(results) == 0:
        raise ValueError("run_health_checks: results must be non-empty")
    if not isinstance(demo_degraded_allowed, bool):
        raise TypeError("run_health_checks: demo_degraded_allowed must be a bool")
    resolved: HealthRuntimeMode | None = None if mode is None else HealthRuntimeMode(mode)
    if demo_degraded_allowed and resolved is not HealthRuntimeMode.DEMO:
        raise ValueError("run_health_checks: demo_degraded_allowed can only be set in DEMO mode")
    has_degraded = any(r.status == STATUS_DEGRADED for r in results)
    passing = _is_complete_passing_set(results) and (
        not has_degraded or _degraded_is_allowed(resolved, demo_degraded_allowed)
    )
    return HealthVerdict(
        is_no_trade=not passing,
        reason_code="OK" if passing else RejectionReason.HEALTH_CHECK_FAILED.value,
        results=tuple(results),
        mode=resolved,
        demo_degraded_allowed=demo_degraded_allowed,
    )


__all__ = [
    "ALL_CHECK_NAMES",
    "CHECK_MARKET_FEED_FRESHNESS",
    "CHECK_LAST_CLOSED_CANDLE_TIME",
    "CHECK_WS_CONNECTION_STATE",
    "CHECK_USER_DATA_STREAM_STATE",
    "CHECK_REST_ERROR_RATE",
    "CHECK_RECONCILIATION_DRIFT",
    "CHECK_DB_WRITES",
    "CHECK_TELEGRAM_DELIVERY",
    "CHECK_UNPROTECTED_POSITIONS",
    "CHECK_ORPHANED_ORDERS",
    "STATUS_PASS",
    "STATUS_FAIL",
    "STATUS_DEGRADED",
    "HealthCheckResult",
    "HealthRuntimeMode",
    "HealthVerdict",
    "JournalLike",
    "NotifierLike",
    "check_not_applicable",
    "check_telegram_delivery_observed",
    "health_check_event",
    "check_market_feed_freshness",
    "check_last_closed_candle_time",
    "check_ws_connection_state",
    "check_user_data_stream_state",
    "check_rest_error_rate",
    "check_reconciliation_drift",
    "check_db_writes",
    "check_telegram_delivery",
    "check_unprotected_positions",
    "check_orphaned_orders",
    "run_health_checks",
]
