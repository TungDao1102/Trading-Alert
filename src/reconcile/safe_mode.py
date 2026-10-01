"""SAFE_MODE controller (Phase 8, plan 08-04, task 3).

Per D-03: any divergence between local intent and exchange truth
forces SAFE_MODE. While in SAFE_MODE, new entries are blocked with
`RECONCILIATION_REQUIRED`; monitoring and reconciliation continue to
run. Exit requires a fresh, clean three-source compare plus a
journaled restore event (Pitfall 4: a boolean flip without both is
rejected).

The module composes with `src/risk/gating.py:evaluate_risk` — the
guard returns a `SafeModeVerdict` that the risk pipeline can short-
circuit on. The risk pipeline's fail-closed posture is preserved:
SAFE_MODE blocks entries, never places orders.

The module is dependency-free: stdlib + `src/domain/enums.py` only.
No Binance SDK, no SQLAlchemy, no Pydantic, no Polars.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from src.domain.enums import RejectionReason, SystemMode

# --------------------------------------------------------------------------- #
# Scheduled tick cadence (FLAGGED ASSUMPTION, RECON-01 unclassified).
#
# The operator tunes this only before a soak epoch starts, never
# mid-epoch. The value is a documented constant — not an env var —
# so a mid-soak change is a code change, not a config drift.
#
# 60s default per RESEARCH A2: a 4H/1H swing-trading system has
# orders of magnitude of headroom for a 60s REST tick; tighter
# cadences waste rate-limit budget without changing the safety
# posture.
# --------------------------------------------------------------------------- #

SAFE_MODE_TICK_SECONDS: int = 60


# --------------------------------------------------------------------------- #
# Adapter + journal protocols — the minimum surface SAFE_MODE needs.
# --------------------------------------------------------------------------- #


class AdapterLike(Protocol):
    """Anything that quacks like the project adapter for SAFE_MODE.

    The real `BinanceUsdmAdapter` satisfies this; tests inject a
    fake that records calls. The protocol is intentionally narrow —
    SAFE_MODE only needs to re-fetch the three truth snapshots to
    verify a clean exit.
    """

    async def snapshot_open_normal_orders(self, *, symbol: str | None = None) -> list[Any]: ...

    async def snapshot_open_algo_orders(self, *, symbol: str | None = None) -> list[Any]: ...

    async def snapshot_positions(self, *, symbol: str | None = None) -> list[Any]: ...


class JournalLike(Protocol):
    """Anything that quacks like the project journal for SAFE_MODE.

    The real journal layer satisfies this; tests inject a fake that
    records events. The protocol is intentionally narrow — SAFE_MODE
    only needs to record the enter/exit transitions.
    """

    def record(self, event: Any) -> None: ...


# --------------------------------------------------------------------------- #
# Frozen dataclasses — the public SAFE_MODE contract.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SafeModeVerdict:
    """Discriminated PASS-or-NO_TRADE envelope emitted by `guard_new_entries`.

    `is_no_trade=True` carries `RECONCILIATION_REQUIRED` in
    `reason_code` (the canonical RejectionReason for SAFE_MODE
    blocks). `is_no_trade=False` is the PASS verdict with
    `reason_code=None` — never a RejectionReason, so a pass cannot be
    confused with a rejection.
    """

    is_no_trade: bool
    reason_code: str | None

    def __post_init__(self) -> None:
        if self.reason_code is None:
            if self.is_no_trade:
                raise ValueError(
                    "SafeModeVerdict: is_no_trade=True requires RECONCILIATION_REQUIRED"
                )
            return
        if self.reason_code not in {r.value for r in RejectionReason}:
            raise ValueError(f"SafeModeVerdict: unknown reason_code {self.reason_code!r}")
        if self.is_no_trade and self.reason_code != RejectionReason.RECONCILIATION_REQUIRED.value:
            raise ValueError("SafeModeVerdict: is_no_trade=True requires RECONCILIATION_REQUIRED")


# --------------------------------------------------------------------------- #
# Controller.
# --------------------------------------------------------------------------- #


class SafeModeController:
    """SAFE_MODE enter / guard / exit state machine.

    The controller is the single owner of the SAFE_MODE flag. The
    scheduled reconciler tick calls `enter_safe_mode` on any
    divergence and `exit_safe_mode` only after a fresh clean
    three-source compare plus a journaled restore event.

    Args:
        adapter: The exchange-truth adapter (Protocol-typed; the
            real `BinanceUsdmAdapter` satisfies this).
        journal: The journal layer (Protocol-typed; the real journal
            satisfies this).
        compare_fn: The compare function (default: `compare` from
            `src/reconcile/compare.py`). Injected for testability.
    """

    def __init__(
        self,
        *,
        adapter: AdapterLike,
        journal: JournalLike,
        compare_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._adapter = adapter
        self._journal = journal
        if compare_fn is None:
            from .compare import compare as _compare

            self._compare = _compare
        else:
            self._compare = compare_fn
        self._in_safe_mode: bool = False
        self._entered_at_utc: datetime | None = None
        self._entered_reason: str | None = None

    @property
    def in_safe_mode(self) -> bool:
        """True when the controller is currently in SAFE_MODE."""
        return self._in_safe_mode

    @property
    def entered_at_utc(self) -> datetime | None:
        """UTC datetime of the SAFE_MODE entry, or None if not in SAFE_MODE."""
        return self._entered_at_utc

    @property
    def entered_reason(self) -> str | None:
        """Reason string of the SAFE_MODE entry, or None if not in SAFE_MODE."""
        return self._entered_reason

    def enter_safe_mode(self, *, reason: str, now_utc: datetime | None = None) -> None:
        """Enter SAFE_MODE on any divergence.

        Idempotent: re-entering with the same reason is a no-op (the
        controller is already in SAFE_MODE). Re-entering with a
        different reason updates the reason string and journals a
        new enter event (the previous divergence is still active).

        Args:
            reason: A short string describing the divergence that
                triggered the entry (e.g., the divergence kind).
            now_utc: The current UTC-aware datetime. If None, uses
                `datetime.now(UTC)`.
        """
        effective_now = now_utc if now_utc is not None else datetime.now(UTC)
        if effective_now.tzinfo is None:
            raise ValueError("now_utc must be UTC-aware")
        if effective_now.utcoffset() != _ZERO_TIMEDELTA:
            raise ValueError("now_utc must be UTC, not offset-aware")
        if self._in_safe_mode:
            # Already in SAFE_MODE — update reason if it changed.
            if self._entered_reason != reason:
                self._entered_reason = reason
                self._journal_safe_mode_event(
                    event_type="SAFE_MODE_REENTER",
                    reason=reason,
                    now_utc=effective_now,
                )
            return
        self._in_safe_mode = True
        self._entered_at_utc = effective_now
        self._entered_reason = reason
        self._journal_safe_mode_event(
            event_type="SAFE_MODE_ENTER",
            reason=reason,
            now_utc=effective_now,
        )

    def guard_new_entries(self, trade_plan: Any) -> SafeModeVerdict:
        """Block new entries while in SAFE_MODE.

        Composes with `src/risk/gating.py:evaluate_risk` — the risk
        pipeline short-circuits on this verdict. The trade_plan
        argument is accepted (and ignored) so the call site mirrors
        the risk pipeline's signature.

        Args:
            trade_plan: The candidate TradePlan (ignored — the
                guard is a pure state check).

        Returns:
            `SafeModeVerdict(is_no_trade=True, reason_code=
            RECONCILIATION_REQUIRED)` when in SAFE_MODE; otherwise
            `SafeModeVerdict(is_no_trade=False, reason_code=None)` (PASS).
        """
        if self._in_safe_mode:
            return SafeModeVerdict(
                is_no_trade=True,
                reason_code=RejectionReason.RECONCILIATION_REQUIRED.value,
            )
        return SafeModeVerdict(
            is_no_trade=False,
            reason_code=None,
        )

    async def exit_safe_mode(
        self,
        *,
        local_open_orders: list[Any] | None = None,
        local_open_algos: list[Any] | None = None,
        local_open_positions: list[Any] | None = None,
        local_intent_fn: Callable[[], tuple[list[Any], list[Any], list[Any]]] | None = None,
        now_utc: datetime | None = None,
    ) -> bool:
        """Exit SAFE_MODE only after a fresh clean three-source compare.

        Per Pitfall 4: a boolean flip without both a clean compare
        AND a journaled restore event is rejected. The function
        re-fetches the three truth snapshots, runs the compare, and
        only exits when the diff is clean.

        Args:
            local_open_orders: The current local open-order intent.
            local_open_algos: The current local open-algo intent.
            local_open_positions: The current local open-position
                intent.
            local_intent_fn: Optional zero-arg callable returning
                `(orders, algos, positions)` fetched at exit time
                (same tick as the truth fetch). When supplied it
                takes precedence over the list arguments, so a stale
                caller snapshot cannot produce a vacuous clean exit.
            now_utc: The current UTC-aware datetime. If None, uses
                `datetime.now(UTC)`.

        Returns:
            True when the exit succeeded (clean compare + journaled
            restore event). False when the compare still shows
            divergences (the controller stays in SAFE_MODE).
        """
        if not self._in_safe_mode:
            return True  # already out
        effective_now = now_utc if now_utc is not None else datetime.now(UTC)
        if effective_now.tzinfo is None:
            raise ValueError("now_utc must be UTC-aware")
        if effective_now.utcoffset() != _ZERO_TIMEDELTA:
            raise ValueError("now_utc must be UTC, not offset-aware")

        if local_intent_fn is not None:
            local_open_orders, local_open_algos, local_open_positions = local_intent_fn()

        # Re-fetch the three truth snapshots.
        truth_normal = await self._adapter.snapshot_open_normal_orders()
        truth_algos = await self._adapter.snapshot_open_algo_orders()
        truth_positions = await self._adapter.snapshot_positions()

        diff = self._compare(
            local_open_orders=local_open_orders or [],
            local_open_algos=local_open_algos or [],
            local_open_positions=local_open_positions or [],
            truth_normal_orders=truth_normal,
            truth_algo_orders=truth_algos,
            truth_positions=truth_positions,
        )
        if not diff.agreement:
            # Still divergent — stay in SAFE_MODE.
            return False

        # Clean compare + journaled restore event: exit.
        self._in_safe_mode = False
        self._journal_safe_mode_event(
            event_type="SAFE_MODE_EXIT",
            reason="clean_three_source_compare",
            now_utc=effective_now,
        )
        self._entered_at_utc = None
        self._entered_reason = None
        return True

    # ----- internal helpers ---------------------------------------------- #

    def _journal_safe_mode_event(self, *, event_type: str, reason: str, now_utc: datetime) -> None:
        """Record one SAFE_MODE transition as a JournalEvent.

        The journal layer is the audit trail; the controller never
        mutates state without journaling first (D-05 extended).
        """
        from src.domain.journal import JournalEvent, content_hash_event_id

        entity_id = SystemMode.SAFE_MODE.value
        payload_json = _build_payload_json(
            {
                "reason": reason,
                "system_mode": SystemMode.SAFE_MODE.value,
            }
        )
        event = JournalEvent(
            # Content hash (D-10, F-412): two different transitions at the
            # same millisecond must not share an id.
            journal_event_id=content_hash_event_id(
                prefix="safe_mode",
                event_type=event_type,
                entity_id=entity_id,
                occurred_at_utc=now_utc,
                payload_json=payload_json,
            ),
            occurred_at_utc=now_utc,
            event_type=event_type,
            entity_type="SystemMode",
            entity_id=entity_id,
            correlation_id="reconcile_safe_mode",
            payload_json=payload_json,
        )
        self._journal.record(event)


# --------------------------------------------------------------------------- #
# Internal helpers.
# --------------------------------------------------------------------------- #

_ZERO_TIMEDELTA = timedelta(0)


def _build_payload_json(payload: dict[str, Any]) -> str:
    """Compact JSON serialisation for journal payloads (DATA_MODEL §5)."""
    import json

    return json.dumps(payload, separators=(",", ":"), default=str)


__all__ = [
    "SAFE_MODE_TICK_SECONDS",
    "SafeModeController",
    "SafeModeVerdict",
    "AdapterLike",
    "JournalLike",
]
