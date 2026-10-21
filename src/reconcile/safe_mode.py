"""SAFE_MODE controller (Phase 8, plan 08-04, task 3).

Per D-03: any divergence between local intent and exchange truth
forces SAFE_MODE. While in SAFE_MODE, new entries are blocked with
`RECONCILIATION_REQUIRED`; monitoring and reconciliation continue to
run. Exit is an explicit, operator-attributed, fail-closed act (Phase 20, plan 20-15, D-15,
F-711): see `SafeModeController.exit_safe_mode`. A boolean flip, a restart, a timer or a
recovered feed never exits.

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

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol, Self

from src.domain.enums import RejectionReason, SystemMode

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


class LocalIntentLike(Protocol):
    """The local side of one compare (`src.reconcile.local_intent.LocalIntent` satisfies it)."""

    @property
    def orders(self) -> Sequence[Any]: ...

    @property
    def algos(self) -> Sequence[Any]: ...

    @property
    def positions(self) -> Sequence[Any]: ...


class ExitRefusal(StrEnum):
    """Why an operator exit was refused (D-15, 20-REVIEW-RESOLUTIONS T-E rows 1-5).

    The codes are the only content of a `SAFE_MODE_EXIT_REFUSED` journal row: never an exception
    text, which may carry a connection string.
    """

    OPERATOR_ID_MISSING = "OPERATOR_ID_MISSING"
    LOCAL_SOURCE_UNREADABLE = "LOCAL_SOURCE_UNREADABLE"
    BINANCE_READ_FAILED = "BINANCE_READ_FAILED"
    COMPARE_NOT_CLEAN = "COMPARE_NOT_CLEAN"
    UNKNOWN_INTENT_PRESENT = "UNKNOWN_INTENT_PRESENT"
    BLOCKING_PROTECTION_STATE = "BLOCKING_PROTECTION_STATE"
    PENDING_ACTION_PRESENT = "PENDING_ACTION_PRESENT"
    READINESS_UNREADABLE = "READINESS_UNREADABLE"


@dataclass(frozen=True)
class ExitReadiness:
    """Row 5 of the exit readiness list: what must be zero before SAFE_MODE may end.

    A field is the COUNT found by a successful read. `None` means "could not be read", which
    refuses the exit (`READINESS_UNREADABLE`) and is never read as zero.

    Attributes:
        unknown_intents: unresolved execution intents of any status (INTENDED, SENT, UNKNOWN).
        blocking_plans: plans in UNPROTECTED, CLOSE_REQUIRED or CLOSE_FAILED.
        open_pending_actions: protective actions still PENDING in the durable queue.
    """

    unknown_intents: int | None
    blocking_plans: int | None
    open_pending_actions: int | None


@dataclass(frozen=True)
class ExitDecision:
    """The outcome of one `exit_safe_mode` call; truthy exactly when SAFE_MODE was left."""

    exited: bool
    refusals: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.exited


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
        # The last operator exit (D-15): audit metadata only, NOT authentication. Kept across a
        # later entry so the persisted state still says who last left SAFE_MODE and when.
        self._last_exit_operator_id: str | None = None
        self._last_exit_at_utc: datetime | None = None
        # True from the moment the in-memory state changed until the store accepted it, so a
        # failed save (or a failed journal write before it) is retried by the next enter call.
        self._persist_pending: bool = False
        # Counts every enter_safe_mode call that passed validation. An exit awaits Binance reads
        # on the same event loop as the reconcile loop; an entry that lands meanwhile means a
        # divergence was found after the exit's reads began, so the exit is refused.
        self._enter_calls: int = 0

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
        try:
            state = state_store.load()
            controller = cls.rehydrate(
                adapter=adapter, journal=journal, compare_fn=compare_fn, state=state
            )
        except Exception as exc:
            controller = cls(
                adapter=adapter, journal=journal, compare_fn=compare_fn, state_store=state_store
            )
            controller._in_safe_mode = True
            controller._entered_at_utc = now_utc
            controller._entered_reason = SAFE_MODE_STATE_UNREADABLE
            try:
                controller._record_event(
                    event_type=SAFE_MODE_STATE_UNREADABLE,
                    payload={"error_type": type(exc).__name__},
                    now_utc=now_utc,
                )
            except Exception:  # noqa: S110 - best-effort audit; the fail-closed state is set
                pass
            return controller
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
                "entered_reason": text or None, "last_exit_operator_id": text or None,
                "last_exit_at_utc": ISO UTC text or None}`, or None. The three-key row written
                by plan 20-06 (no `last_exit_*` keys) is read as `last_exit_*` None.

        Raises:
            ValueError: the mapping is neither the five-key nor the three-key format (any other
                key set, including a partial `last_exit_*` pair), a value has the wrong
                type, a datetime is naive or not UTC, SAFE_MODE is set without its entry time
                or reason, or SAFE_MODE is off while an entry time or reason is still set.
        """
        controller = cls(adapter=adapter, journal=journal, compare_fn=compare_fn)
        if state is None:
            return controller
        parsed = _parse_state(state)
        controller._in_safe_mode = parsed.in_safe_mode
        controller._entered_at_utc = parsed.entered_at_utc
        controller._entered_reason = parsed.entered_reason
        controller._last_exit_operator_id = parsed.last_exit_operator_id
        controller._last_exit_at_utc = parsed.last_exit_at_utc
        return controller

    def state_snapshot(self) -> dict[str, str | bool | None]:
        """The persistable SAFE_MODE state (the `rehydrate` input format, five keys).

        When the controller is not in SAFE_MODE the entry time and reason are reported as None.
        The last operator exit (`last_exit_operator_id`, `last_exit_at_utc`) is reported in both
        states; both are None until an operator has exited once.
        """
        last_exit_at = (
            None if self._last_exit_at_utc is None else self._last_exit_at_utc.isoformat()
        )
        if not self._in_safe_mode:
            return {
                "in_safe_mode": False,
                "entered_at_utc": None,
                "entered_reason": None,
                "last_exit_operator_id": self._last_exit_operator_id,
                "last_exit_at_utc": last_exit_at,
            }
        return {
            "in_safe_mode": True,
            "entered_at_utc": (
                None if self._entered_at_utc is None else self._entered_at_utc.isoformat()
            ),
            "entered_reason": self._entered_reason,
            "last_exit_operator_id": self._last_exit_operator_id,
            "last_exit_at_utc": last_exit_at,
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
        if not isinstance(reason, str) or reason == "":
            raise ValueError("reason must be a non-empty string")
        effective_now = now_utc if now_utc is not None else datetime.now(UTC)
        _require_utc(effective_now)
        self._enter_calls += 1
        if self._in_safe_mode:
            # Already in SAFE_MODE — update reason if it changed.
            if self._entered_reason != reason:
                self._entered_reason = reason
                self._persist_pending = self._state_store is not None
                self._journal_safe_mode_event(
                    event_type="SAFE_MODE_REENTER",
                    reason=reason,
                    now_utc=effective_now,
                )
                self._persist(now_utc=effective_now)
            elif self._persist_pending:
                self._persist(now_utc=effective_now)
            return
        self._in_safe_mode = True
        self._entered_at_utc = effective_now
        self._entered_reason = reason
        self._persist_pending = self._state_store is not None
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
        operator_id: str,
        local_intent_fn: Callable[[], LocalIntentLike],
        readiness: Callable[[], ExitReadiness],
        now_utc: datetime,
    ) -> ExitDecision:
        """Leave SAFE_MODE only as an explicit, operator-attributed, fail-closed act (D-15).

        A boolean flip, a restart, a timer, a recovered feed and a closed intent never exit
        SAFE_MODE; this call is the only way. There is no list argument a caller can leave empty
        (F-711): the only local input is `local_intent_fn`. The readiness list is closed
        (20-REVIEW-RESOLUTIONS T-E, rows 1-5; rows 6 and 7 wait for owner decision O-B, plan
        20-25):

          1. `operator_id` is a non-empty string. It is audit metadata, NOT authentication; an
             allow-list must exist before any LIVE path opens (Phase 23/24).
          2. `local_intent_fn()` returned its three sequences. A raising or incomplete source
             BLOCKS the exit; an empty sequence counts only after a successful read.
          3. Positions, open orders and algo orders were read from Binance during THIS call.
          4. Compare v2 on those fresh reads agrees, and no `enter_safe_mode` call landed while the
             reads were awaited (the reconcile loop shares the event loop; such an entry is a
             divergence the reads predate, and refuses as `COMPARE_NOT_CLEAN`).
          5. `readiness()` read every count and all are zero: no unresolved intent, no UNPROTECTED /
             CLOSE_REQUIRED / CLOSE_FAILED plan, no PENDING protective action.

        Every refusal found in one pass is returned and journaled as `SAFE_MODE_EXIT_REFUSED`
        (codes only, best-effort); the state does not change. On success the order is: journal
        `SAFE_MODE_EXIT` with the operator id FIRST, persist the exit state SECOND, flip memory
        LAST (17-REVIEW WR-03, D-14, D-15), so a failure of either write propagates with the
        controller still in SAFE_MODE and a later call can still exit.

        Args:
            operator_id: Who exits (audit only).
            local_intent_fn: Zero-argument callable returning the local intent
                (`.orders`, `.algos`, `.positions`) read at exit time.
            readiness: Zero-argument callable returning the row-5 counts.
            now_utc: The current UTC-aware datetime (required; no wall-clock fallback).

        Returns:
            `ExitDecision(exited=True)` when SAFE_MODE was left (also when it was already off),
            otherwise `ExitDecision(exited=False, refusals=...)` and the controller stays in
            SAFE_MODE.

        Raises:
            ValueError: `now_utc` is naive or not UTC (a caller bug).
            Exception: whatever the `SAFE_MODE_EXIT` journal write or the state store raised; the
                controller is still in SAFE_MODE.
        """
        _require_utc(now_utc)
        if not self._in_safe_mode:
            return ExitDecision(exited=True)

        refusals: list[str] = []

        # Row 1: the operator id.
        if not isinstance(operator_id, str) or operator_id.strip() == "":
            refusals.append(ExitRefusal.OPERATOR_ID_MISSING.value)

        enter_calls_before = self._enter_calls

        # Row 2: the local intent source, read successfully or the exit is blocked.
        local = _read_local_intent(local_intent_fn)
        if local is None:
            refusals.append(ExitRefusal.LOCAL_SOURCE_UNREADABLE.value)

        # Row 3: fresh successful Binance reads in this call.
        truth = await self._read_truth()
        if truth is None:
            refusals.append(ExitRefusal.BINANCE_READ_FAILED.value)

        # Row 4: compare v2 on those two reads. A SAFE_MODE entry that landed while the reads were
        # awaited (the reconcile loop shares the event loop) is a divergence these reads predate.
        entered_meanwhile = self._enter_calls != enter_calls_before
        compare_dirty = (
            local is not None and truth is not None and not self._compare_is_clean(local, truth)
        )
        if entered_meanwhile or compare_dirty:
            refusals.append(ExitRefusal.COMPARE_NOT_CLEAN.value)

        # Row 5: the readiness counts.
        refusals.extend(_readiness_refusals(readiness))

        if refusals:
            self._journal_exit_refused(refusals=refusals, now_utc=now_utc)
            return ExitDecision(exited=False, refusals=tuple(refusals))

        # All rows hold. Journal FIRST (a failure propagates, still in SAFE_MODE), persist
        # SECOND (same), flip memory LAST.
        self._record_event(
            event_type="SAFE_MODE_EXIT",
            payload={
                "reason": "clean_three_source_compare",
                "system_mode": SystemMode.SAFE_MODE.value,
                "operator_id": operator_id,
            },
            now_utc=now_utc,
        )
        if self._state_store is not None:
            self._state_store.save(
                {
                    "in_safe_mode": False,
                    "entered_at_utc": None,
                    "entered_reason": None,
                    "last_exit_operator_id": operator_id,
                    "last_exit_at_utc": now_utc.isoformat(),
                },
                now_utc=now_utc,
            )
        self._in_safe_mode = False
        self._entered_at_utc = None
        self._entered_reason = None
        self._last_exit_operator_id = operator_id
        self._last_exit_at_utc = now_utc
        self._persist_pending = False
        return ExitDecision(exited=True)

    # ----- internal helpers ---------------------------------------------- #

    async def _read_truth(self) -> tuple[tuple[Any, ...], tuple[Any, ...], tuple[Any, ...]] | None:
        """The three Binance snapshots read now, or None when any read failed (fail closed)."""
        try:
            normal = await self._adapter.snapshot_open_normal_orders()
            algos = await self._adapter.snapshot_open_algo_orders()
            positions = await self._adapter.snapshot_positions()
            if normal is None or algos is None or positions is None:
                return None
            return tuple(normal), tuple(algos), tuple(positions)
        except Exception:
            return None

    def _compare_is_clean(
        self,
        local: tuple[tuple[Any, ...], tuple[Any, ...], tuple[Any, ...]],
        truth: tuple[tuple[Any, ...], tuple[Any, ...], tuple[Any, ...]],
    ) -> bool:
        """True only when the compare ran and reported agreement; an error is never clean."""
        try:
            diff = self._compare(
                local_open_orders=local[0],
                local_open_algos=local[1],
                local_open_positions=local[2],
                truth_normal_orders=truth[0],
                truth_algo_orders=truth[1],
                truth_positions=truth[2],
            )
            return bool(getattr(diff, "agreement", False) is True)
        except Exception:
            return False

    def _journal_exit_refused(self, *, refusals: Sequence[str], now_utc: datetime) -> None:
        """Journal a refused exit, codes only. Best-effort: the controller stays in SAFE_MODE."""
        try:
            self._record_event(
                event_type="SAFE_MODE_EXIT_REFUSED",
                payload={"refusals": list(refusals), "system_mode": SystemMode.SAFE_MODE.value},
                now_utc=now_utc,
            )
        except Exception:  # noqa: S110 - the refusal already holds; the audit row is a bonus
            pass

    def _persist(self, *, now_utc: datetime) -> None:
        """Save `state_snapshot()` to the attached store; a failure propagates (fail closed)."""
        if self._state_store is None:
            return
        # `_persist_pending` stays True when `save` raises, so the next enter call retries it.
        self._state_store.save(self.state_snapshot(), now_utc=now_utc)
        self._persist_pending = False

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


def _read_local_intent(
    local_intent_fn: Callable[[], LocalIntentLike],
) -> tuple[tuple[Any, ...], tuple[Any, ...], tuple[Any, ...]] | None:
    """The local intent as three tuples, or None when the source is unreadable (row 2, F-711).

    A raising source, a missing result or a missing sequence is never turned into an empty list:
    an empty sequence counts only when the read itself succeeded.
    """
    try:
        intent = local_intent_fn()
        orders = intent.orders
        algos = intent.algos
        positions = intent.positions
        if orders is None or algos is None or positions is None:
            return None
        return tuple(orders), tuple(algos), tuple(positions)
    except Exception:
        return None


def _is_count(value: object) -> bool:
    """True for a read count: a non-negative int (a bool is not a count)."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _readiness_refusals(readiness: Callable[[], ExitReadiness]) -> list[str]:
    """The row-5 refusal codes: an unreadable field refuses, a non-zero count refuses."""
    try:
        counts = readiness()
        unknown = counts.unknown_intents
        blocking = counts.blocking_plans
        pending = counts.open_pending_actions
    except Exception:
        return [ExitRefusal.READINESS_UNREADABLE.value]
    refusals: list[str] = []
    if not (_is_count(unknown) and _is_count(blocking) and _is_count(pending)):
        refusals.append(ExitRefusal.READINESS_UNREADABLE.value)
    if _is_count(unknown) and unknown != 0:
        refusals.append(ExitRefusal.UNKNOWN_INTENT_PRESENT.value)
    if _is_count(blocking) and blocking != 0:
        refusals.append(ExitRefusal.BLOCKING_PROTECTION_STATE.value)
    if _is_count(pending) and pending != 0:
        refusals.append(ExitRefusal.PENDING_ACTION_PRESENT.value)
    return refusals


#: Plan states that keep SAFE_MODE on (row 5): exposure that is not (or cannot be) protected.
#: Compared by string value so this module imports nothing from `src.execution`.
_BLOCKING_PLAN_STATES: frozenset[str] = frozenset({"UNPROTECTED", "CLOSE_REQUIRED", "CLOSE_FAILED"})


def build_exit_readiness(
    *,
    unresolved_intents_fn: Callable[[], Iterable[Any]],
    protections_fn: Callable[[], Iterable[Any]],
    open_pending_fn: Callable[[], Iterable[Any]],
) -> ExitReadiness:
    """Compose the row-5 counts from three plain providers (D-15, T-E).

    The composition passes `ExecutionIntentStore.list_unresolved_intents`,
    `ProtectionCoordinator.protections` and `PendingActionStore.list_open`. A provider that raises,
    returns None or returns something that is not an iterable makes ITS field None ("could not be
    read"), which `exit_safe_mode` refuses as `READINESS_UNREADABLE`; it is never read as zero.

    - `unknown_intents`: every unresolved intent counts, whatever its status (INTENDED, SENT or
      UNKNOWN), because any of them may still hold an order or an exposure.
    - `blocking_plans`: plans whose `state` is UNPROTECTED, CLOSE_REQUIRED or CLOSE_FAILED.
    - `open_pending_actions`: every open pending protective action.
    """
    return ExitReadiness(
        unknown_intents=_count_rows(unresolved_intents_fn, lambda _row: True),
        blocking_plans=_count_rows(protections_fn, _plan_blocks),
        open_pending_actions=_count_rows(open_pending_fn, lambda _row: True),
    )


def _plan_blocks(plan: Any) -> bool:
    """True when the plan's state keeps SAFE_MODE on; raises when the view has no state."""
    state = plan.state
    name = getattr(state, "value", state)
    if not isinstance(name, str) or name == "":
        raise ValueError("a plan state must be a non-empty string")
    return name in _BLOCKING_PLAN_STATES


def _count_rows(provider: Callable[[], Iterable[Any]], counts: Callable[[Any], bool]) -> int | None:
    """How many rows of `provider()` satisfy `counts`, or None when the read failed."""
    try:
        rows = provider()
        if rows is None or isinstance(rows, str | bytes):
            return None
        return sum(1 for row in rows if counts(row))
    except Exception:
        return None


_CORE_STATE_KEYS = frozenset({"in_safe_mode", "entered_at_utc", "entered_reason"})
_EXIT_STATE_KEYS = frozenset({"last_exit_operator_id", "last_exit_at_utc"})
#: The five-key format written since plan 20-15 (D-15).
_STATE_KEYS = _CORE_STATE_KEYS | _EXIT_STATE_KEYS


@dataclass(frozen=True)
class _ParsedState:
    """A validated persisted SAFE_MODE state."""

    in_safe_mode: bool
    entered_at_utc: datetime | None
    entered_reason: str | None
    last_exit_operator_id: str | None
    last_exit_at_utc: datetime | None


def _parse_utc(raw: object, name: str) -> datetime | None:
    """An ISO-8601 UTC-aware datetime from text, or None for None (`ValueError` on anything off)."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"{name} must be ISO-8601 text, got {type(raw).__name__}")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        raise ValueError(f"{name} is not an ISO-8601 datetime") from None
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be UTC-aware, got naive datetime")
    if parsed.utcoffset() != _ZERO_TIMEDELTA:
        raise ValueError(f"{name} must be UTC, not offset-aware")
    return parsed


def _parse_state(state: object) -> _ParsedState:
    """Validate a persisted SAFE_MODE mapping (fail closed, `ValueError` on anything off).

    Two key sets are accepted: the five-key format, and the three-key row written by plan 20-06
    (read as `last_exit_*` None). Any other key set is refused.
    """
    if not isinstance(state, Mapping):
        raise ValueError(f"SAFE_MODE state must be a mapping, got {type(state).__name__}")
    keys = set(state)
    if keys != _STATE_KEYS and keys != _CORE_STATE_KEYS:
        raise ValueError(
            f"SAFE_MODE state keys differ: unknown={sorted(map(str, keys - _STATE_KEYS))} "
            f"missing={sorted(_CORE_STATE_KEYS - keys)} "
            f"partial_exit_keys={sorted(map(str, keys & _EXIT_STATE_KEYS))}"
        )
    in_safe_mode = state["in_safe_mode"]
    if not isinstance(in_safe_mode, bool):
        raise ValueError(f"in_safe_mode must be a bool, got {type(in_safe_mode).__name__}")
    entered_at = _parse_utc(state["entered_at_utc"], "entered_at_utc")
    reason = state["entered_reason"]
    if reason is not None and not isinstance(reason, str):
        raise ValueError(f"entered_reason must be text or None, got {type(reason).__name__}")
    if in_safe_mode:
        if entered_at is None:
            raise ValueError("in_safe_mode is true but entered_at_utc is missing")
        if reason is None:
            raise ValueError("in_safe_mode is true but entered_reason is missing")
    elif entered_at is not None or reason is not None:
        raise ValueError("in_safe_mode is false but an entry time or reason is still set")

    last_operator: str | None = None
    last_exit_at: datetime | None = None
    if keys == _STATE_KEYS:
        raw_operator = state["last_exit_operator_id"]
        last_exit_at = _parse_utc(state["last_exit_at_utc"], "last_exit_at_utc")
        if raw_operator is not None:
            if not isinstance(raw_operator, str) or raw_operator.strip() == "":
                raise ValueError("last_exit_operator_id must be non-empty text or None")
            last_operator = raw_operator
        if (last_operator is None) != (last_exit_at is None):
            raise ValueError("last_exit_operator_id and last_exit_at_utc must be set together")
    return _ParsedState(in_safe_mode, entered_at, reason, last_operator, last_exit_at)


def _build_payload_json(payload: dict[str, Any]) -> str:
    """Compact JSON serialisation for journal payloads (DATA_MODEL §5)."""
    import json

    return json.dumps(payload, separators=(",", ":"), default=str)


__all__ = [
    "SAFE_MODE_STATE_UNREADABLE",
    "AdapterLike",
    "build_exit_readiness",
    "ExitDecision",
    "ExitReadiness",
    "ExitRefusal",
    "JournalLike",
    "LocalIntentLike",
    "SafeModeController",
    "SafeModeStateStore",
    "SafeModeVerdict",
]
