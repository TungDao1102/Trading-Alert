"""Cancel-only orphan sweeper (Phase 8, plan 08-04, task 2).

Per D-03: the sweeper is the cancel-only path that resolves
ORPHAN_PROTECTIVE divergences. It NEVER places a new order under any
input (Pitfall 1: never auto-place rescue protection for unprotected
positions). The sweeper requires authoritative position-zero
verification (T-8-30) before any cancel — two consecutive zero reads
OR position-plus-order-truth agreement.

The sweeper is journal-first (D-05 extended): the pre-image is
journaled BEFORE the cancel call, the post-image is journaled AFTER.
A cancel that fails to journal the pre-image is rejected (the audit
trail is the safety net). It is not one of the four risk-reducing controls of D-16: an
orphan reduce-only / closePosition leg cannot open exposure, so it keeps its journal-first
pre-image.

Phase 20 plan 20-11: a cancel is not counted until a query shows it (D-17, F-502). After the
cancel the algo order is queried by its client id (`confirm_algo_cancel`); the post-image is
journaled, and the orphan counted as swept, only for CANCELED or GONE_NOT_CANCELED (nothing
rests under the id any more). Any other verdict journals `cancel_unverified`, and the orphan is
reported as skipped, so the next tick looks again. Every skipped cancel also leaves a best-effort
`SWEEP_SKIPPED` row (IN-14, D-03): symbol, algo id and a reason code, never exception text.

A manual close outside the system (G4-035) can end two ways and the sweeper relies on neither:
the exchange auto-cancels the closePosition legs when the position goes flat (the probe finds
nothing, `already_gone`), or the legs stay as orphans (two zero reads, a verified cancel).

The module is dependency-free: stdlib + `src/domain/*` + sibling
modules + `src/execution/cancel_verification.py` (a read-only query helper with no
placement method) only. No Binance SDK, no SQLAlchemy, no Pydantic, no Polars.
The adapter is consumed via Protocol-typed surfaces; only
`src/adapters/binance_usdm.py` imports the SDK.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from src.domain.algo_status import classify_algo_status
from src.domain.journal import JournalEvent, content_hash_event_id
from src.execution.cancel_verification import (
    PROVEN_GONE,
    CancelDetail,
    CancelVerdict,
    confirm_algo_cancel,
)

# --------------------------------------------------------------------------- #
# Adapter + journal protocols — the minimum surface the sweeper needs.
# --------------------------------------------------------------------------- #


class AdapterLike(Protocol):
    """Anything that quacks like the project adapter for cancel paths.

    The real `BinanceUsdmAdapter` satisfies this; tests inject a
    fake that records calls. The protocol is intentionally narrow —
    the sweeper only needs the cancel + query-by-ID surface.
    """

    async def query_algo_order_by_client(self, *, client_algo_id: str) -> Any: ...

    async def cancel_algo_order(self, *, symbol: str, client_algo_id: str) -> None: ...


class JournalLike(Protocol):
    """Anything that quacks like the project journal for the sweeper."""

    def record(self, event: Any) -> None: ...


# --------------------------------------------------------------------------- #
# Position verifier protocol.
# --------------------------------------------------------------------------- #


PositionVerifier = Callable[..., Any]
"""Caller-supplied function that returns the current position amount.

The signature is intentionally loose (the sweeper does not import
the adapter's PositionSnapshot type). The function MUST return a
Decimal-like value (truthy/falsy comparison works for the zero check).
"""


# --------------------------------------------------------------------------- #
# Frozen dataclasses — the public sweeper contract.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SweepSkip:
    """One orphan protective the sweeper refused to cancel.

    `reason` is a short string describing why the cancel was skipped
    (e.g., "transient_position_gap" when the first position read was
    non-zero). The skip is journaled so the next tick can re-attempt
    with fresh data.
    """

    symbol: str
    client_algo_id: str
    reason: str


@dataclass(frozen=True)
class SweepOutcome:
    """Result of `OrphanSweeper.sweep(...)`.

    `swept_count` is the number of orphan protectives cancelled.
    `cancelled` is the list of `(symbol, client_algo_id)` tuples
    that were successfully cancelled. `skipped` is the list of
    `SweepSkip` records for orphans the sweeper refused to act on.
    `already_gone` lists orphans whose probe returned `found=False`
    (already absent on the exchange — no cancel issued, counted
    separately from real cancels).
    """

    swept_count: int
    cancelled: tuple[tuple[str, str], ...]
    skipped: tuple[SweepSkip, ...]
    already_gone: tuple[tuple[str, str], ...] = ()


# --------------------------------------------------------------------------- #
# Sweeper.
# --------------------------------------------------------------------------- #


class OrphanSweeper:
    """Cancel-only orphan-protective sweeper.

    The sweeper iterates `CompareDiff.orphan_protectives`, verifies
    position-zero across two consecutive reads (T-8-30), cancels via
    the adapter cancel path, and journals pre/post images as
    `JournalEvent`s.

    Args:
        adapter: The exchange-truth adapter (Protocol-typed; the
            real `BinanceUsdmAdapter` satisfies this).
        journal: The journal layer (Protocol-typed; the real journal
            satisfies this).
        now_utc: The current UTC-aware datetime. If None, uses
            `datetime.now(UTC)` at sweep time.
    """

    def __init__(
        self,
        *,
        adapter: AdapterLike,
        journal: JournalLike,
        now_utc: datetime | None = None,
    ) -> None:
        self._adapter = adapter
        self._journal = journal
        self._now_utc = now_utc

    async def sweep(
        self,
        diff: Any,
        *,
        position_verifier: PositionVerifier,
        now_utc: datetime | None = None,
    ) -> SweepOutcome:
        """Sweep the orphan protectives in `diff`.

        Args:
            diff: A `CompareDiff` from `src/reconcile/compare.py`.
            position_verifier: Caller-supplied function that returns
                the current position amount for a symbol. The
                sweeper calls it twice per orphan (consecutive zero
                reads required). May be sync or async — a coroutine
                result is awaited.
            now_utc: Per-sweep timestamp. Resolved inside `sweep`
                (never pinned at construction for long-lived
                sweepers): explicit value wins, else the constructor
                test hook, else `datetime.now(UTC)`.

        Returns:
            A `SweepOutcome` carrying the cancelled and skipped
            lists. The sweeper NEVER raises on a single cancel
            failure — it journals the failure and continues with
            the next orphan.
        """
        if now_utc is not None:
            effective_now = now_utc
        elif self._now_utc is not None:
            effective_now = self._now_utc
        else:
            effective_now = datetime.now(UTC)
        if effective_now.tzinfo is None:
            raise ValueError("now_utc must be UTC-aware")
        if effective_now.utcoffset() != _ZERO_TIMEDELTA:
            raise ValueError("now_utc must be UTC, not offset-aware")

        cancelled: list[tuple[str, str]] = []
        skipped: list[SweepSkip] = []
        already_gone: list[tuple[str, str]] = []

        for orphan in diff.orphan_protectives:
            symbol = orphan.symbol
            client_algo_id = orphan.client_algo_id

            # Authoritative position-zero verification (T-8-30):
            # two consecutive zero reads required. A single non-zero
            # read blocks the cancel (transient gap protection).
            first_read = position_verifier(symbol=symbol)
            second_read = position_verifier(symbol=symbol)
            if _is_awaitable(first_read):
                first_read = await first_read
            if _is_awaitable(second_read):
                second_read = await second_read
            if not (_is_zero_like(first_read) and _is_zero_like(second_read)):
                skip_reason = (
                    f"transient_position_gap: first_read={first_read!r} second_read={second_read!r}"
                )
                skipped.append(
                    SweepSkip(
                        symbol=symbol,
                        client_algo_id=client_algo_id,
                        reason=skip_reason,
                    )
                )
                self._record_skip_best_effort(
                    symbol=symbol,
                    client_algo_id=client_algo_id,
                    reason_code=_REASON_TRANSIENT_GAP,
                    now_utc=effective_now,
                )
                continue

            # Query-by-ID first (T-8-32): verify the algo still
            # exists before issuing the cancel. A not-found probe
            # is treated as a successful prior sweep (no cancel
            # needed, no error).
            try:
                probe = await self._adapter.query_algo_order_by_client(
                    client_algo_id=client_algo_id
                )
            except Exception as exc:
                # Exception TYPE only: an SDK network error embeds the request URL
                # (signature included) and the journal is append-only (T-18-14).
                self._record_failure_best_effort(
                    symbol=symbol,
                    client_algo_id=client_algo_id,
                    reason=f"probe_failed: {type(exc).__name__}",
                    now_utc=effective_now,
                )
                skipped.append(
                    SweepSkip(
                        symbol=symbol,
                        client_algo_id=client_algo_id,
                        reason=f"probe_failed: {type(exc).__name__}",
                    )
                )
                self._record_skip_best_effort(
                    symbol=symbol,
                    client_algo_id=client_algo_id,
                    reason_code=f"probe_failed: {type(exc).__name__}",
                    now_utc=effective_now,
                )
                continue
            if not getattr(probe, "found", False):
                self._journal.record(
                    self._build_failure_event(
                        symbol=symbol,
                        client_algo_id=client_algo_id,
                        reason="already_gone_no_cancel_needed",
                        now_utc=effective_now,
                        phase="already_gone",
                    )
                )
                already_gone.append((symbol, client_algo_id))
                continue

            try:
                # Journal the pre-image BEFORE the cancel (D-05 extended).
                pre_event = self._build_pre_image_event(
                    symbol=symbol,
                    client_algo_id=client_algo_id,
                    probe=probe,
                    now_utc=effective_now,
                )
                self._journal.record(pre_event)

                # Issue the cancel.
                await self._adapter.cancel_algo_order(
                    symbol=symbol,
                    client_algo_id=client_algo_id,
                )
            except Exception as exc:
                self._record_failure_best_effort(
                    symbol=symbol,
                    client_algo_id=client_algo_id,
                    reason=f"cancel_failed: {type(exc).__name__}",
                    now_utc=effective_now,
                )
                skipped.append(
                    SweepSkip(
                        symbol=symbol,
                        client_algo_id=client_algo_id,
                        reason=f"cancel_failed: {type(exc).__name__}",
                    )
                )
                self._record_skip_best_effort(
                    symbol=symbol,
                    client_algo_id=client_algo_id,
                    reason_code=f"cancel_failed: {type(exc).__name__}",
                    now_utc=effective_now,
                )
                continue

            # The cancel call returned, which proves nothing (-2011 maps to the same None,
            # D-17, F-502): ask the exchange. Only a query that shows the order canceled, or
            # no longer resting, counts the orphan as swept.
            detail = CancelDetail()
            verdict = await confirm_algo_cancel(
                self._adapter, client_algo_id=client_algo_id, detail=detail
            )
            if verdict not in PROVEN_GONE:
                self._record_failure_best_effort(
                    symbol=symbol,
                    client_algo_id=client_algo_id,
                    reason=f"cancel_unverified: {verdict.value}",
                    now_utc=effective_now,
                    phase="cancel_unverified",
                    verdict=verdict,
                    detail=detail,
                )
                skipped.append(
                    SweepSkip(
                        symbol=symbol,
                        client_algo_id=client_algo_id,
                        reason=f"cancel_unverified: {verdict.value}",
                    )
                )
                self._record_skip_best_effort(
                    symbol=symbol,
                    client_algo_id=client_algo_id,
                    reason_code=f"cancel_unverified: {verdict.value}",
                    now_utc=effective_now,
                )
                continue

            # The algo order is gone whatever happens to the post-image write, so the
            # orphan is counted as cancelled either way.
            cancelled.append((symbol, client_algo_id))
            try:
                # Journal the post-image AFTER the cancel.
                post_event = self._build_post_image_event(
                    symbol=symbol,
                    client_algo_id=client_algo_id,
                    now_utc=effective_now,
                    verdict=verdict,
                )
                self._journal.record(post_event)
            except Exception as exc:
                self._record_failure_best_effort(
                    symbol=symbol,
                    client_algo_id=client_algo_id,
                    reason=f"post_image_failed: {type(exc).__name__}",
                    now_utc=effective_now,
                )

        return SweepOutcome(
            swept_count=len(cancelled),
            cancelled=tuple(cancelled),
            skipped=tuple(skipped),
            already_gone=tuple(already_gone),
        )

    # ----- internal helpers ---------------------------------------------- #

    def _record_failure_best_effort(
        self,
        *,
        symbol: str,
        client_algo_id: str,
        reason: str,
        now_utc: datetime,
        phase: str = "sweep_failed",
        verdict: CancelVerdict | None = None,
        detail: CancelDetail | None = None,
    ) -> None:
        """Journal a failure event; a journal error must not end the sweep.

        The failure is already reported in `SweepOutcome` (skipped / cancelled),
        so a second journal failure here must not abort the remaining orphans.
        """
        try:
            self._journal.record(
                self._build_failure_event(
                    symbol=symbol,
                    client_algo_id=client_algo_id,
                    reason=reason,
                    now_utc=now_utc,
                    phase=phase,
                    verdict=verdict,
                    detail=detail,
                )
            )
        except Exception:  # best effort by design, see the docstring
            return

    def _record_skip_best_effort(
        self,
        *,
        symbol: str,
        client_algo_id: str,
        reason_code: str,
        now_utc: datetime,
    ) -> None:
        """Journal one `SWEEP_SKIPPED` row for a cancel the sweeper did not make (IN-14, D-03).

        The payload holds the symbol, the algo id and a reason code (an exception CLASS name at
        most, never its text). A journal failure is swallowed: the skip is already in
        `SweepOutcome` and must not end the sweep.
        """
        payload_json = _build_payload_json(
            {"symbol": symbol, "client_algo_id": client_algo_id, "reason": reason_code}
        )
        try:
            self._journal.record(
                JournalEvent(
                    journal_event_id=content_hash_event_id(
                        prefix="sweep_skipped",
                        event_type=EVENT_SWEEP_SKIPPED,
                        entity_id=client_algo_id,
                        occurred_at_utc=now_utc,
                        payload_json=payload_json,
                    ),
                    occurred_at_utc=now_utc,
                    event_type=EVENT_SWEEP_SKIPPED,
                    entity_type="OpenAlgoOrder",
                    entity_id=client_algo_id,
                    correlation_id="reconcile_orphan_sweep",
                    payload_json=payload_json,
                )
            )
        except Exception:  # best effort by design, see the docstring
            return

    def _build_pre_image_event(
        self,
        *,
        symbol: str,
        client_algo_id: str,
        probe: Any,
        now_utc: datetime,
    ) -> JournalEvent:
        """Build the pre-cancel JournalEvent carrying the orphan state."""
        payload = {
            "symbol": symbol,
            "client_algo_id": client_algo_id,
            "algo_status": getattr(probe, "algo_status", None),
            "algo_status_class": classify_algo_status(getattr(probe, "algo_status", None)).value,
            "update_time_utc": _iso(getattr(probe, "update_time_utc", None)),
            "phase": "pre_cancel",
        }
        payload_json = _build_payload_json(payload)
        return JournalEvent(
            journal_event_id=content_hash_event_id(
                prefix="orphan_sweep",
                event_type="ORPHAN_SWEEP",
                entity_id=client_algo_id,
                occurred_at_utc=now_utc,
                payload_json=payload_json,
            ),
            occurred_at_utc=now_utc,
            event_type="ORPHAN_SWEEP",
            entity_type="OpenAlgoOrder",
            entity_id=client_algo_id,
            correlation_id="reconcile_orphan_sweep",
            payload_json=payload_json,
        )

    def _build_failure_event(
        self,
        *,
        symbol: str,
        client_algo_id: str,
        reason: str,
        now_utc: datetime,
        phase: str = "sweep_failed",
        verdict: CancelVerdict | None = None,
        detail: CancelDetail | None = None,
    ) -> JournalEvent:
        payload: dict[str, Any] = {
            "symbol": symbol,
            "client_algo_id": client_algo_id,
            "cancelled": False,
            "reason": reason,
            "phase": phase,
        }
        if verdict is not None:
            payload["verdict"] = verdict.value
        if detail is not None and detail.observed_status is not None:
            payload["observed_status"] = detail.observed_status
        if detail is not None and detail.error_type is not None:
            payload["error_type"] = detail.error_type
        payload_json = _build_payload_json(payload)
        return JournalEvent(
            journal_event_id=content_hash_event_id(
                prefix="orphan_sweep",
                event_type="ORPHAN_SWEEP",
                entity_id=client_algo_id,
                occurred_at_utc=now_utc,
                payload_json=payload_json,
            ),
            occurred_at_utc=now_utc,
            event_type="ORPHAN_SWEEP",
            entity_type="OpenAlgoOrder",
            entity_id=client_algo_id,
            correlation_id="reconcile_orphan_sweep",
            payload_json=payload_json,
        )

    def _build_post_image_event(
        self,
        *,
        symbol: str,
        client_algo_id: str,
        now_utc: datetime,
        verdict: CancelVerdict | None = None,
    ) -> JournalEvent:
        """Build the post-cancel JournalEvent carrying the cancel outcome.

        `verdict` (plan 20-11) is the post-cancel query result, CANCELED or GONE_NOT_CANCELED;
        it is left out of the payload when None, which keeps older ids unchanged.
        """
        payload: dict[str, Any] = {
            "symbol": symbol,
            "client_algo_id": client_algo_id,
            "cancelled": True,
            "cancelled_at_utc": _iso(now_utc),
            "phase": "post_cancel",
        }
        if verdict is not None:
            payload["verdict"] = verdict.value
        payload_json = _build_payload_json(payload)
        return JournalEvent(
            journal_event_id=content_hash_event_id(
                prefix="orphan_sweep",
                event_type="ORPHAN_SWEEP",
                entity_id=client_algo_id,
                occurred_at_utc=now_utc,
                payload_json=payload_json,
            ),
            occurred_at_utc=now_utc,
            event_type="ORPHAN_SWEEP",
            entity_type="OpenAlgoOrder",
            entity_id=client_algo_id,
            correlation_id="reconcile_orphan_sweep",
            payload_json=payload_json,
        )


# --------------------------------------------------------------------------- #
# Internal helpers.
# --------------------------------------------------------------------------- #

_ZERO_TIMEDELTA = timedelta(0)

EVENT_SWEEP_SKIPPED = "SWEEP_SKIPPED"
_REASON_TRANSIENT_GAP = "transient_position_gap"


def _is_awaitable(value: Any) -> bool:
    import inspect

    return inspect.isawaitable(value)


def _is_zero_like(value: Any) -> bool:
    """True when `value` is zero (Decimal / int / float / str).

    The position verifier returns a Decimal-like value; we accept
    any numeric type and compare against zero. A None or non-numeric
    value is treated as "not zero" (fail closed — the sweeper
    refuses to cancel on ambiguous data).
    """
    if value is None:
        return False
    try:
        result: bool = value == 0
    except TypeError:
        return False
    return result


def _iso(value: Any) -> str | None:
    """ISO-8601 serialisation for journal payloads (None-safe)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _build_payload_json(payload: dict[str, Any]) -> str:
    """Compact JSON serialisation for journal payloads (DATA_MODEL §5)."""
    import json

    return json.dumps(payload, separators=(",", ":"), default=str)


__all__ = [
    "EVENT_SWEEP_SKIPPED",
    "OrphanSweeper",
    "SweepOutcome",
    "SweepSkip",
    "AdapterLike",
    "JournalLike",
    "PositionVerifier",
]
