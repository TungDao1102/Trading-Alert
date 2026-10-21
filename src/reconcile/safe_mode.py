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

SAFE_MODE is durable (Phase 20, plan 20-06, D-14, F-127): `enter_safe_mode` saves
`state_snapshot()` through the injected `SafeModeStateStore` and `SafeModeController.load` restores
it at start, failing closed into SAFE_MODE when the store cannot be read. The store is a Protocol,
so this module imports nothing from `src.persistence`.

The module is dependency-free: stdlib + `src/domain/enums.py` only.
No Binance SDK, no SQLAlchemy, no Pydantic, no Polars.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, Self

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

#: The `entered_reason` of a controller whose persisted state could not be read or parsed at start
#: (D-14, research C14): an unreadable store must only ever make the system more restricted.
SAFE_MODE_STATE_UNREADABLE: str = "SAFE_MODE_STATE_UNREADABLE"


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


class SafeModeStateStore(Protocol):
    """Durable memory of the SAFE_MODE state (D-14).

    The real implementation is `src.persistence.safe_mode_store.PgSafeModeStateStore`; tests inject
    an in-memory fake. The mapping is exactly the `SafeModeController.state_snapshot()` format.
    """

    def save(self, state: Mapping[str, str | bool | None], *, now_utc: datetime) -> None:
        """Persist one SAFE_MODE state; raise on any failure (the caller fails closed)."""
        ...

    def load(self) -> Mapping[str, str | bool | None] | None:
        """The latest persisted state, or None when nothing was ever persisted."""
        ...


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
        state_store: The durable SAFE_MODE store (D-14). None keeps the controller in-memory
            only (`is_durable` is False); the reconcile loop and startup refuse such a controller.
    """

    def __init__(
        self,
        *,
        adapter: AdapterLike,
        journal: JournalLike,
        compare_fn: Callable[..., Any] | None = None,
        state_store: SafeModeStateStore | None = None,
    ) -> None:
        self._adapter = adapter
        self._journal = journal
        self._state_store = state_store
        if compare_fn is None:
            from .compare import compare as _compare

            self._compare = _compare
        else:
            self._compare = compare_fn
        self._in_safe_mode: bool = False
        self._entered_at_utc: datetime | None = None
        self._entered_reason: str | None = None

    @classmethod
    def load(
        cls,
        *,
        adapter: AdapterLike,
        journal: JournalLike,
        state_store: SafeModeStateStore,
        now_utc: datetime,
        compare_fn: Callable[..., Any] | None = None,
    ) -> Self:
        """Start a controller from the durable store, failing closed (D-14, research C14).

        `state_store.load()` returning None means nothing was ever persisted: the default
        controller (not in SAFE_MODE). A persisted state is restored through the `rehydrate`
        parsing. Any exception from the store, or a malformed mapping, starts the controller IN
        SAFE_MODE with reason `SAFE_MODE_STATE_UNREADABLE` and entry time `now_utc`: a restart
        never reads SAFE_MODE as off. The failure is journaled best-effort with the exception
        TYPE name only, never its message (it may carry a connection string).

        Args:
            adapter: The exchange-truth adapter (as for the constructor).
            journal: The journal layer (as for the constructor).
            state_store: The durable store; attached to the returned controller.
            now_utc: The current UTC-aware datetime (the entry time of an unreadable start).
            compare_fn: The compare function (as for the constructor).

        Raises:
            ValueError: `now_utc` is naive or not UTC (a caller bug, not a store failure).
        """
        _require_utc(now_utc)
        controller = cls.rehydrate(
            adapter=adapter, journal=journal, compare_fn=compare_fn, state=state_store.load()
        )
        controller._state_store = state_store
        return controller

    @classmethod
    def rehydrate(
        cls,
        *,
        adapter: AdapterLike,
        journal: JournalLike,
        compare_fn: Callable[..., Any] | None = None,
        state: Mapping[str, Any] | None,
    ) -> Self:
        """Rebuild a controller from a persisted `state_snapshot()` mapping (D-22, F-606).

        A restart must never silently read SAFE_MODE as off (research C14). `state=None` means
        nothing was ever persisted and returns the default controller (not in SAFE_MODE). Any
        other value must be exactly the `state_snapshot()` format; anything malformed raises
        `ValueError` instead of defaulting (fail closed). Restoring writes nothing to the
        journal: the original enter transition was already journaled.

        The mapping is plain data: this module imports nothing from `src.persistence`.

        Args:
            adapter: The exchange-truth adapter (as for the constructor).
            journal: The journal layer (as for the constructor).
            compare_fn: The compare function (as for the constructor).
            state: `{"in_safe_mode": bool, "entered_at_utc": ISO UTC text or None,
                "entered_reason": text or None}`, or None.

        Raises:
            ValueError: the mapping is not exactly the snapshot format, a value has the wrong
                type, a datetime is naive or not UTC, SAFE_MODE is set without its entry time
                or reason, or SAFE_MODE is off while an entry time or reason is still set.
        """
        controller = cls(adapter=adapter, journal=journal, compare_fn=compare_fn)
        if state is None:
            return controller
        in_safe_mode, entered_at_utc, entered_reason = _parse_state(state)
        controller._in_safe_mode = in_safe_mode
        controller._entered_at_utc = entered_at_utc
        controller._entered_reason = entered_reason
        return controller

    def state_snapshot(self) -> dict[str, str | bool | None]:
        """The persistable SAFE_MODE state (the `rehydrate` input format).

        When the controller is not in SAFE_MODE the entry time and reason are reported as None.
        """
        if not self._in_safe_mode:
            return {"in_safe_mode": False, "entered_at_utc": None, "entered_reason": None}
        return {
            "in_safe_mode": True,
            "entered_at_utc": (
                None if self._entered_at_utc is None else self._entered_at_utc.isoformat()
            ),
            "entered_reason": self._entered_reason,
        }

    @property
    def is_durable(self) -> bool:
        """True when a `SafeModeStateStore` is attached (the reconcile loop and startup need it)."""
        return self._state_store is not None

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

        With a state store attached the new state is saved after the journal write (D-14). The
        in-memory flag flips first, so a failing journal or store write propagates with the
        controller still in SAFE_MODE (fail closed). The next call, even with the same reason,
        retries the save until the store accepts it.

        Args:
            reason: A short, non-empty string describing the divergence that
                triggered the entry (e.g., the divergence kind).
            now_utc: The current UTC-aware datetime. If None, uses
                `datetime.now(UTC)`.

        Raises:
            ValueError: `reason` is empty or not text (nothing changes), or `now_utc` is naive or
                not UTC.
        """
        effective_now = now_utc if now_utc is not None else datetime.now(UTC)
        _require_utc(effective_now)
        if self._in_safe_mode:
            # Already in SAFE_MODE — update reason if it changed.
            if self._entered_reason != reason:
                self._entered_reason = reason
                self._journal_safe_mode_event(
                    event_type="SAFE_MODE_REENTER",
                    reason=reason,
                    now_utc=effective_now,
                )
                self._persist(now_utc=effective_now)
            return
        self._in_safe_mode = True
        self._entered_at_utc = effective_now
        self._entered_reason = reason
        self._journal_safe_mode_event(
            event_type="SAFE_MODE_ENTER",
            reason=reason,
            now_utc=effective_now,
        )
        self._persist(now_utc=effective_now)

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

        # Clean compare + journaled restore event: exit. The opposite order to
        # `enter_safe_mode` on purpose (17-REVIEW WR-03): the exit is journaled FIRST, so a
        # journal failure propagates with the controller still in SAFE_MODE (fail closed)
        # and a later retry can still exit; entering flips first so a failure there also
        # fails closed.
        self._journal_safe_mode_event(
            event_type="SAFE_MODE_EXIT",
            reason="clean_three_source_compare",
            now_utc=effective_now,
        )
        self._in_safe_mode = False
        self._entered_at_utc = None
        self._entered_reason = None
        return True

    # ----- internal helpers ---------------------------------------------- #

    def _persist(self, *, now_utc: datetime) -> None:
        """Save `state_snapshot()` to the attached store; a failure propagates (fail closed)."""
        if self._state_store is None:
            return
        self._state_store.save(self.state_snapshot(), now_utc=now_utc)

    def _journal_safe_mode_event(self, *, event_type: str, reason: str, now_utc: datetime) -> None:
        """Record one SAFE_MODE transition as a JournalEvent.

        The journal layer is the audit trail; the controller never
        mutates state without journaling first (D-05 extended).
        """
        self._record_event(
            event_type=event_type,
            payload={
                "reason": reason,
                "system_mode": SystemMode.SAFE_MODE.value,
            },
            now_utc=now_utc,
        )

    def _record_event(self, *, event_type: str, payload: dict[str, Any], now_utc: datetime) -> None:
        """Record one SystemMode JournalEvent with the given payload."""
        from src.domain.journal import JournalEvent, content_hash_event_id

        entity_id = SystemMode.SAFE_MODE.value
        payload_json = _build_payload_json(payload)
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


def _require_utc(value: datetime) -> None:
    """Raise `ValueError` unless `value` is a UTC-aware datetime."""
    if value.tzinfo is None:
        raise ValueError("now_utc must be UTC-aware")
    if value.utcoffset() != _ZERO_TIMEDELTA:
        raise ValueError("now_utc must be UTC, not offset-aware")


_STATE_KEYS = frozenset({"in_safe_mode", "entered_at_utc", "entered_reason"})


def _parse_state(state: object) -> tuple[bool, datetime | None, str | None]:
    """Validate a persisted SAFE_MODE mapping (fail closed, `ValueError` on anything off)."""
    if not isinstance(state, Mapping):
        raise ValueError(f"SAFE_MODE state must be a mapping, got {type(state).__name__}")
    if set(state) != _STATE_KEYS:
        raise ValueError(
            f"SAFE_MODE state keys differ: unknown={sorted(map(str, set(state) - _STATE_KEYS))} "
            f"missing={sorted(_STATE_KEYS - set(state))}"
        )
    in_safe_mode = state["in_safe_mode"]
    if not isinstance(in_safe_mode, bool):
        raise ValueError(f"in_safe_mode must be a bool, got {type(in_safe_mode).__name__}")
    raw_at = state["entered_at_utc"]
    reason = state["entered_reason"]
    if raw_at is None:
        entered_at: datetime | None = None
    else:
        if not isinstance(raw_at, str):
            raise ValueError(f"entered_at_utc must be ISO-8601 text, got {type(raw_at).__name__}")
        try:
            entered_at = datetime.fromisoformat(raw_at)
        except ValueError:
            raise ValueError("entered_at_utc is not an ISO-8601 datetime") from None
        if entered_at.tzinfo is None:
            raise ValueError("entered_at_utc must be UTC-aware, got naive datetime")
        if entered_at.utcoffset() != _ZERO_TIMEDELTA:
            raise ValueError("entered_at_utc must be UTC, not offset-aware")
    if reason is not None and not isinstance(reason, str):
        raise ValueError(f"entered_reason must be text or None, got {type(reason).__name__}")
    if in_safe_mode:
        if entered_at is None:
            raise ValueError("in_safe_mode is true but entered_at_utc is missing")
        if reason is None:
            raise ValueError("in_safe_mode is true but entered_reason is missing")
    elif entered_at is not None or reason is not None:
        raise ValueError("in_safe_mode is false but an entry time or reason is still set")
    return in_safe_mode, entered_at, reason


def _build_payload_json(payload: dict[str, Any]) -> str:
    """Compact JSON serialisation for journal payloads (DATA_MODEL §5)."""
    import json

    return json.dumps(payload, separators=(",", ":"), default=str)


__all__ = [
    "SAFE_MODE_STATE_UNREADABLE",
    "SAFE_MODE_TICK_SECONDS",
    "SafeModeController",
    "SafeModeStateStore",
    "SafeModeVerdict",
    "AdapterLike",
    "JournalLike",
]
