"""Live enablement controller (Phase 9, plan 09-03).

Per D-04: deployment default is `LIVE_ORDERS_DISABLED`; live execution
requires an explicit operator enable step. The controller owns the
`LIVE_ORDERS_DISABLED` flag. ENABLE is journaled before the flag flips (an enable
without its audit record must not happen). DISABLE is risk-reducing, so it acts first
and journals afterwards (Phase 20 plan 20-08, D-16, F-702): the flag flips, then the
record goes to the journal or, if the journal is down, to a local spill. The controller
exposes `guard_placement` returning an `EnablementVerdict`.

The module imports only stdlib, `src/domain` and the pure-Python `src/ops/risk_first` /
`src/ops/spill` helpers. No analytics import, no Binance SDK, no SQLAlchemy, no Pydantic,
no Polars of its own.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol, Self

from src.domain.enums import KillGateState
from src.domain.journal import JournalEvent, content_hash_event_id
from src.ops.risk_first import record_after

if TYPE_CHECKING:
    from src.ops.spill import LocalSpill

# --------------------------------------------------------------------------- #
# Reason code constants — enablement-specific vocabulary.
# --------------------------------------------------------------------------- #

_DISABLED = "DISABLED"


# --------------------------------------------------------------------------- #
# Protocol-typed journal surface — the controller never imports the journal.
# --------------------------------------------------------------------------- #


class JournalLike(Protocol):
    """Anything that quacks like the project journal for enablement.

    The real journal layer satisfies this; tests inject a fake that
    records events. The protocol is intentionally narrow — enablement
    only needs to record the enable/disable transitions.
    """

    def record(self, event: Any) -> None: ...


# --------------------------------------------------------------------------- #
# Frozen dataclass — the public enablement contract.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EnablementVerdict:
    """Discriminated PASS-or-NO_TRADE envelope emitted by `guard_placement`.

    `is_no_trade=True` carries `DISABLED` in `reason_code` (the canonical
    enablement rejection). `is_no_trade=False` carries `reason_code=None`
    — never a RejectionReason, so a pass cannot be confused with a
    rejection.
    """

    is_no_trade: bool
    reason_code: str | None

    def __post_init__(self) -> None:
        if self.reason_code is None:
            if self.is_no_trade:
                raise ValueError("EnablementVerdict: is_no_trade=True requires reason_code")
            return
        if not isinstance(self.reason_code, str) or self.reason_code == "":
            raise ValueError("reason_code must be a non-empty string")
        if self.is_no_trade and self.reason_code != _DISABLED:
            raise ValueError(
                f"EnablementVerdict: is_no_trade=True requires "
                f"reason_code={_DISABLED!r}, got {self.reason_code!r}"
            )


# --------------------------------------------------------------------------- #
# Controller.
# --------------------------------------------------------------------------- #


class LiveEnablementController:
    """LIVE_ORDERS_DISABLED flag owner: enable is journal-first, disable acts first.

    The controller is the single owner of the `LIVE_ORDERS_DISABLED`
    flag. The default is `True` (disabled) — live execution requires an
    explicit operator enable step. The ENABLE transition is journaled
    BEFORE the flag flips. The DISABLE transition flips the flag FIRST and
    is journaled afterwards, through the local spill when the journal is
    down (D-16, F-702), so a database outage can never keep live orders on.

    Args:
        journal: The journal layer (Protocol-typed; the real journal
            satisfies this).
        spill: Optional local spill that keeps the disable audit record
            when the journal is down. Without one a failing journal raises
            `AuditRecordLost` AFTER the flag flipped.
    """

    def __init__(self, *, journal: JournalLike, spill: LocalSpill | None = None) -> None:
        self._journal = journal
        self._spill = spill
        self._disabled: bool = True
        self._enabled_at_utc: datetime | None = None
        self._operator_id: str | None = None

    @classmethod
    def rehydrate(
        cls,
        *,
        journal: JournalLike,
        state: Mapping[str, Any] | None,
        spill: LocalSpill | None = None,
    ) -> Self:
        """Rebuild a controller from a persisted `state_snapshot()` mapping (D-22, F-606).

        `state=None` means nothing was ever persisted and returns the default controller
        (live orders disabled). Any other value must be exactly the `state_snapshot()` format;
        anything malformed raises `ValueError` instead of defaulting (fail closed). Restoring
        writes nothing to the journal: the enable or disable transition that produced the
        persisted state was already journaled by the controller that made it.

        The mapping is plain data: this module imports nothing from `src.persistence`.

        Args:
            journal: The journal layer (as for the constructor).
            spill: The optional local spill (as for the constructor).
            state: `{"disabled": bool, "enabled_at_utc": ISO UTC text or None,
                "operator_id": text or None}`, or None.

        Raises:
            ValueError: the mapping is not exactly the snapshot format, a value has the wrong
                type, a datetime is naive or not UTC, an enabled state lacks its operator id or
                enable time, or a disabled state still carries either.
        """
        controller = cls(journal=journal, spill=spill)
        if state is None:
            return controller
        disabled, enabled_at_utc, operator_id = _parse_state(state)
        controller._disabled = disabled
        controller._enabled_at_utc = enabled_at_utc
        controller._operator_id = operator_id
        return controller

    def state_snapshot(self) -> dict[str, str | bool | None]:
        """The persistable enablement state (the `rehydrate` input format).

        When live orders are disabled the enable time and operator id are reported as None.
        """
        if self._disabled:
            return {"disabled": True, "enabled_at_utc": None, "operator_id": None}
        return {
            "disabled": False,
            "enabled_at_utc": (
                None if self._enabled_at_utc is None else self._enabled_at_utc.isoformat()
            ),
            "operator_id": self._operator_id,
        }

    @property
    def is_disabled(self) -> bool:
        """True when `LIVE_ORDERS_DISABLED` is true (default)."""
        return self._disabled

    @property
    def enabled_at_utc(self) -> datetime | None:
        """UTC datetime of the enable transition, or None if disabled."""
        return self._enabled_at_utc

    @property
    def operator_id(self) -> str | None:
        """Operator id who enabled live orders, or None if disabled."""
        return self._operator_id

    def guard_placement(self, *, plan_hash: str) -> EnablementVerdict:
        """Block placement when `LIVE_ORDERS_DISABLED` is true.

        Composes with `src/execution/gates.py:decide_placement` — the
        manager short-circuits on this verdict before any gate
        evaluation. The `plan_hash` argument is accepted (and ignored)
        so the call site mirrors the gate pipeline's signature.

        Args:
            plan_hash: The candidate plan hash (ignored — the guard is
                a pure state check).

        Returns:
            `EnablementVerdict(is_no_trade=True, reason_code=DISABLED)`
            when disabled; otherwise
            `EnablementVerdict(is_no_trade=False, reason_code=None)` (PASS).
        """
        if self._disabled:
            return EnablementVerdict(
                is_no_trade=True,
                reason_code=_DISABLED,
            )
        return EnablementVerdict(
            is_no_trade=False,
            reason_code=None,
        )

    def enable(
        self,
        *,
        operator_id: str,
        now_utc: datetime,
        health_verdict: Any,
        kill_gate_state: KillGateState,
    ) -> None:
        """Enable live orders. Journals the transition before flipping the flag.

        Per D-04: only an explicit operator enable with journaled id
        plus timestamp flips the flag. The journal event is recorded
        BEFORE the flag flips (journal-first pattern).

        09-REVIEW WR-08: RED (or unevaluated) health blocks enablement.
        `health_verdict` must be a passing `src.ops.health.HealthVerdict`
        (from `run_health_checks`, structurally complete: one non-FAIL
        result per canonical probe); anything else raises before the
        journal event and the flag stays disabled.

        Args:
            operator_id: The operator id enabling live orders.
            now_utc: The current UTC-aware datetime.
            health_verdict: The aggregate health verdict for this enable.
            kill_gate_state: The EVALUATED research kill-gate state (Phase 10 D-03).

        Kill-gate contract (Phase 10 D-03): `INSUFFICIENT_EDGE` is terminal and never
        auto-clears; it refuses enablement BEFORE any journal write or flag flip, so
        live stays disabled until an explicit human decision record clears it. A value
        that is not a `KillGateState` (unevaluated, None, a plain string) is refused the
        same way. `PASSING_CANDIDATE` only records that evidence exists and NEVER
        authorizes live trading by itself: a separate human decision record is a process
        requirement, and the explicit operator plus passing-health requirements still
        apply. The kill-gate state is deliberately not added to the enable journal
        payload (the Phase 9 event vocabulary is unchanged).

        Raises:
            ValueError: invalid operator id / timestamp, a health
                verdict that is missing or not passing, or a kill-gate state that is
                unevaluated or INSUFFICIENT_EDGE.
        """
        _validate_operator_id(operator_id)
        _validate_utc_aware(now_utc)
        if (
            health_verdict is None
            or getattr(health_verdict, "is_no_trade", True) is not False
            or getattr(health_verdict, "reason_code", None) != "OK"
        ):
            raise ValueError(
                "enable: a passing health verdict is required (RED or "
                "unevaluated health blocks live enablement)"
            )
        if not isinstance(kill_gate_state, KillGateState):
            raise ValueError(
                "enable: an evaluated kill-gate state is required (unevaluated or "
                "non-KillGateState value blocks live enablement)"
            )
        if kill_gate_state is KillGateState.INSUFFICIENT_EDGE:
            raise ValueError(
                "enable: the kill gate is INSUFFICIENT_EDGE terminal; live stays disabled "
                "until an explicit human decision record clears it"
            )

        # Journal first, then flip the flag (enabling is not risk-reducing).
        self._journal.record(
            self._build_enablement_event(
                event_type="LIVE_ORDERS_ENABLED",
                operator_id=operator_id,
                now_utc=now_utc,
                disabled_after=False,
            )
        )
        self._disabled = False
        self._enabled_at_utc = now_utc
        self._operator_id = operator_id

    def disable(self, *, operator_id: str, now_utc: datetime) -> None:
        """Disable live orders. Flips the flag first, journals the transition afterwards.

        Per D-04 the transition is journaled with operator id plus timestamp. Per D-16
        (F-702) disabling is risk-reducing, so it never waits for the journal: the flag
        flips, then the record goes to the journal, or to the local spill when the journal
        is down. A database outage therefore cannot keep live orders enabled.

        Args:
            operator_id: The operator id disabling live orders.
            now_utc: The current UTC-aware datetime.

        Raises:
            ValueError: invalid operator id or timestamp (before any change).
            AuditRecordLost: the flag flipped, but neither the journal nor the spill took the
                audit record (the message names exception classes only).
        """
        _validate_operator_id(operator_id)
        _validate_utc_aware(now_utc)

        # Build the record while the prior state is still known, flip, then record.
        event = self._build_enablement_event(
            event_type="LIVE_ORDERS_DISABLED",
            operator_id=operator_id,
            now_utc=now_utc,
            disabled_after=True,
        )
        self._disabled = True
        self._enabled_at_utc = None
        self._operator_id = None
        record_after(spill=self._spill, journal=self._journal, event=event)

    # ----- internal helpers ---------------------------------------------- #

    def _build_enablement_event(
        self, *, event_type: str, operator_id: str, now_utc: datetime, disabled_after: bool
    ) -> JournalEvent:
        """Build one enable/disable transition as a JournalEvent.

        The journal layer is the audit trail. The payload carries the TARGET
        state explicitly (`live_orders_disabled`, the state after this
        transition) plus the prior state (`live_orders_disabled_before`),
        so the record never contradicts its own event type (09-REVIEW WR-10).
        The event is built BEFORE the flag changes so the prior state is exact.
        """
        payload_json = json.dumps(
            {
                "operator_id": operator_id,
                "live_orders_disabled": disabled_after,
                "live_orders_disabled_before": self._disabled,
            },
            separators=(",", ":"),
        )
        return JournalEvent(
            # 09-REVIEW WR-09: content-hash id (no same-millisecond PK collision).
            journal_event_id=content_hash_event_id(
                prefix="enablement",
                event_type=event_type,
                entity_id="LIVE_ORDERS_DISABLED",
                occurred_at_utc=now_utc,
                payload_json=payload_json,
            ),
            occurred_at_utc=now_utc,
            event_type=event_type,
            entity_type="LiveEnablement",
            entity_id="LIVE_ORDERS_DISABLED",
            correlation_id="execution_enablement",
            payload_json=payload_json,
        )


# --------------------------------------------------------------------------- #
# Internal helpers.
# --------------------------------------------------------------------------- #


_STATE_KEYS = frozenset({"disabled", "enabled_at_utc", "operator_id"})


def _parse_state(state: object) -> tuple[bool, datetime | None, str | None]:
    """Validate a persisted enablement mapping (fail closed, `ValueError` on anything off)."""
    if not isinstance(state, Mapping):
        raise ValueError(f"enablement state must be a mapping, got {type(state).__name__}")
    if set(state) != _STATE_KEYS:
        raise ValueError(
            f"enablement state keys differ: unknown={sorted(map(str, set(state) - _STATE_KEYS))} "
            f"missing={sorted(_STATE_KEYS - set(state))}"
        )
    disabled = state["disabled"]
    if not isinstance(disabled, bool):
        raise ValueError(f"disabled must be a bool, got {type(disabled).__name__}")
    raw_at = state["enabled_at_utc"]
    operator_id = state["operator_id"]
    if raw_at is None:
        enabled_at: datetime | None = None
    else:
        if not isinstance(raw_at, str):
            raise ValueError(f"enabled_at_utc must be ISO-8601 text, got {type(raw_at).__name__}")
        try:
            enabled_at = datetime.fromisoformat(raw_at)
        except ValueError:
            raise ValueError("enabled_at_utc is not an ISO-8601 datetime") from None
        _validate_utc_aware(enabled_at)
    if operator_id is not None and not isinstance(operator_id, str):
        raise ValueError(f"operator_id must be text or None, got {type(operator_id).__name__}")
    if disabled:
        if enabled_at is not None or operator_id is not None:
            raise ValueError("disabled is true but an enable time or operator id is still set")
    else:
        if enabled_at is None:
            raise ValueError("disabled is false but enabled_at_utc is missing")
        if operator_id is None:
            raise ValueError("disabled is false but operator_id is missing")
        _validate_operator_id(operator_id)
    return disabled, enabled_at, operator_id


def _validate_operator_id(operator_id: str) -> None:
    """Reject empty operator ids (D-04 audit-trail discipline)."""
    if not isinstance(operator_id, str) or operator_id == "":
        raise ValueError("operator_id must be a non-empty string")


def _validate_utc_aware(now_utc: datetime) -> None:
    """Reject naive and non-UTC datetimes (D-12)."""
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be UTC-aware, got naive datetime")
    if now_utc.utcoffset() != timedelta(0):
        raise ValueError(f"now_utc must be UTC, got offset {now_utc.utcoffset()}")


__all__ = [
    "LiveEnablementController",
    "EnablementVerdict",
    "JournalLike",
]
