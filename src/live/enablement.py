"""DEMO enablement and the kill-gate switch-off of the live process (plan 24-22; D-27, D-28, Q5).

The execution manager refuses every placement while the enablement controller is disabled (gate
2, `manager.py`), and the manager is not changed (C-2). So the live process has exactly one path
to an enabled controller, `enable_demo`, and exactly one automatic path to a disabled one,
`on_kill_gate_verdict`:

* `enable_demo` is the in-process DEMO enable that ends the start sequence. It raises
  `LiveEnableForbidden` in LIVE (and TESTNET) before it touches the controller; LIVE keeps the
  human operator action. It enables only from a verdict judged for DEMO that is OK (a legacy
  verdict without a mode is refused), with a kill-gate state that was evaluated and is not
  INSUFFICIENT_EDGE (the state comes from the analytics source; this module chooses no default).
  A refusal is journaled with the failing check names and leaves the controller disabled.
  D058: a missing or stale mark price makes `market_feed_freshness` FAIL, so it refuses here.
* A persisted "enabled" is never trusted: `start_disabled` returns a fresh DISABLED controller at
  every start. A persisted enabled (or unreadable) snapshot is journaled as reset and overwritten
  with a disabled snapshot, so a restart never resumes order placement by itself (T-24-66).
* `on_kill_gate_verdict` is the only automatic caller toward `disable()` (operator id
  `KILL_GATE`), and only for INSUFFICIENT_EDGE. Nothing in `src/live` calls `enable()` outside
  `enable_demo` (an AST test pins it), and no health or kill-gate event enables anything.

Known limit: `controller.enable` and `controller.disable` journal through the controller's own
synchronous journal on the event loop thread (the controller is a Phase 9 object). The snapshot
write goes through the `StoreExecutor` writer. A failed snapshot write after a successful enable
is logged and reported in `EnableOutcome.persisted`; it cannot make a later start enabled.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import structlog

from src.adapters.binance_client import Environment
from src.domain.enums import KillGateState, SystemStateKey
from src.domain.journal import JournalEvent, content_hash_event_id
from src.execution.enablement import JournalLike, LiveEnablementController
from src.ops.health import ALL_CHECK_NAMES, STATUS_FAIL, HealthRuntimeMode, HealthVerdict
from src.ops.spill import LocalSpill

log = structlog.get_logger(__name__)

#: The fixed audit id of the in-process DEMO enable (Q5). Not a person; never used in LIVE.
DEMO_RUNTIME_OPERATOR_ID = "DEMO_RUNTIME"
#: The audit id of the automatic switch-off by the research kill gate.
KILL_GATE_OPERATOR_ID = "KILL_GATE"

EVENT_ENABLE_REFUSED = "LIVE_ENABLE_REFUSED"
EVENT_ENABLEMENT_RESET_AT_START = "LIVE_ENABLEMENT_RESET_AT_START"

REASON_ENABLED = "ENABLED"
REASON_ALREADY_ENABLED = "ALREADY_ENABLED"
REASON_VERDICT_NOT_FOR_DEMO = "VERDICT_NOT_FOR_DEMO"
REASON_HEALTH_NOT_OK = "HEALTH_NOT_OK"
REASON_KILL_GATE_UNEVALUATED = "KILL_GATE_UNEVALUATED"
REASON_KILL_GATE_INSUFFICIENT_EDGE = "KILL_GATE_INSUFFICIENT_EDGE"

ACTION_DISABLED = "DISABLED"
ACTION_NO_CHANGE = "NO_CHANGE"
ACTION_ALREADY_DISABLED = "ALREADY_DISABLED"

type Record = Callable[[JournalEvent], Awaitable[None]]
type StoreWrite = Callable[..., Awaitable[Any]]
type StoreRead = Callable[..., Awaitable[Any]]
type Snapshot = Mapping[str, str | bool | None]
type Persist = Callable[[], Awaitable[None]]
type KillGateSource = Callable[[], Awaitable[KillGateState | None]]


class LiveEnableForbidden(RuntimeError):  # noqa: N818 - a refusal of the mode, not an error family
    """`enable_demo` was called for a mode other than DEMO; the controller was not touched."""


class SystemStateStore(Protocol):
    """`PgSystemStateStore` as this module uses it (synchronous; called through the executor)."""

    def append(self, key: SystemStateKey, state: Snapshot, *, now_utc: datetime) -> Any: ...

    def latest(self, key: SystemStateKey) -> Any: ...


@dataclass(frozen=True)
class EnableOutcome:
    """What `enable_demo` did: `failing` names checks (never values), `persisted` the snapshot."""

    enabled: bool
    reason: str
    failing: tuple[str, ...] = ()
    persisted: bool = False


@dataclass(frozen=True)
class KillGateOutcome:
    """What `on_kill_gate_verdict` did."""

    action: str
    state: KillGateState | None


@dataclass(frozen=True)
class StartEnablement:
    """The controller of a start (always DISABLED) and what the stored snapshot said."""

    controller: LiveEnablementController
    persisted_enabled: bool
    persisted_problem: str | None


# --------------------------------------------------------------------------- #
# Journal helpers.
# --------------------------------------------------------------------------- #


def _event(event_type: str, now_utc: datetime, document: Mapping[str, Any]) -> JournalEvent:
    payload_json = json.dumps(document, separators=(",", ":"), sort_keys=True)
    return JournalEvent(
        journal_event_id=content_hash_event_id(
            prefix="live_enablement",
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


def _failing_names(verdict: HealthVerdict) -> tuple[str, ...]:
    """The check names that keep a verdict from being OK: FAIL, missing, and DEGRADED if refused."""
    seen = {r.check_name for r in verdict.results}
    names = [r.check_name for r in verdict.results if r.status == STATUS_FAIL]
    names.extend(name for name in ALL_CHECK_NAMES if name not in seen)
    if not verdict.demo_degraded_allowed:
        names.extend(verdict.degraded_names)
    return tuple(dict.fromkeys(names))


# --------------------------------------------------------------------------- #
# Persistence.
# --------------------------------------------------------------------------- #


async def persist_enablement_snapshot(
    controller: LiveEnablementController,
    *,
    state_store: SystemStateStore,
    write: StoreWrite,
    now_utc: datetime,
) -> None:
    """Append the controller's `state_snapshot()` under `SystemStateKey.LIVE_ENABLEMENT`.

    The write goes through the `StoreExecutor` writer (`write(fn, *args, **kwargs)`). The record
    is evidence of the last state; `start_disabled` never trusts it as an "enabled".
    """
    await write(
        state_store.append,
        SystemStateKey.LIVE_ENABLEMENT,
        controller.state_snapshot(),
        now_utc=now_utc,
    )


async def start_disabled(
    *,
    journal: JournalLike,
    state_store: SystemStateStore,
    read: StoreRead,
    write: StoreWrite,
    record: Record,
    now_utc: datetime,
    spill: LocalSpill | None = None,
) -> StartEnablement:
    """A fresh DISABLED controller, whatever the stored snapshot says (T-24-66).

    A stored snapshot that says enabled, or that is malformed, is journaled
    (`LIVE_ENABLEMENT_RESET_AT_START`, no value echoed) and overwritten with the disabled
    snapshot. An unreachable store raises (the start refuses; it never assumes).
    """
    stored = await read(state_store.latest, SystemStateKey.LIVE_ENABLEMENT)
    persisted_enabled = False
    problem: str | None = None
    if stored is not None:
        try:
            probe = LiveEnablementController.rehydrate(journal=journal, state=stored.state)
            persisted_enabled = not probe.is_disabled
        except ValueError:
            problem = "STORED_ENABLEMENT_STATE_MALFORMED"
    controller = LiveEnablementController(journal=journal, spill=spill)
    if persisted_enabled or problem is not None:
        await record(
            _event(
                EVENT_ENABLEMENT_RESET_AT_START,
                now_utc,
                {"persisted_enabled": persisted_enabled, "problem": problem},
            )
        )
        await persist_enablement_snapshot(
            controller, state_store=state_store, write=write, now_utc=now_utc
        )
    return StartEnablement(
        controller=controller, persisted_enabled=persisted_enabled, persisted_problem=problem
    )


# --------------------------------------------------------------------------- #
# DEMO enable.
# --------------------------------------------------------------------------- #


async def enable_demo(
    *,
    mode: Environment,
    controller: LiveEnablementController,
    health_verdict: HealthVerdict,
    kill_gate_state: KillGateState | None,
    now_utc: datetime,
    record: Record,
    persist: Persist | None = None,
) -> EnableOutcome:
    """The in-process DEMO enable at the end of the start sequence (Q5, D-28).

    Raises:
        LiveEnableForbidden: `mode` is not DEMO (LIVE and TESTNET); nothing was touched.
    """
    if mode is not Environment.DEMO:
        raise LiveEnableForbidden(
            f"enable_demo is DEMO only: mode {getattr(mode, 'value', mode)!s} keeps the human step"
        )
    refusal = _refusal(health_verdict, kill_gate_state)
    if refusal is not None or not isinstance(kill_gate_state, KillGateState):
        # The isinstance test only narrows the type: `_refusal` already refuses a non-state.
        reason, failing = refusal or (REASON_KILL_GATE_UNEVALUATED, ())
        await record(
            _event(
                EVENT_ENABLE_REFUSED,
                now_utc,
                {"failing": list(failing), "mode": mode.value, "reason": reason},
            )
        )
        log.warning("live.enablement.refused", reason=reason, failing=list(failing))
        return EnableOutcome(enabled=False, reason=reason, failing=failing)
    if not controller.is_disabled:
        return EnableOutcome(enabled=True, reason=REASON_ALREADY_ENABLED)
    controller.enable(
        operator_id=DEMO_RUNTIME_OPERATOR_ID,
        now_utc=now_utc,
        health_verdict=health_verdict,
        kill_gate_state=kill_gate_state,
    )
    persisted = False
    if persist is not None:
        try:
            await persist()
            persisted = True
        except Exception as exc:  # noqa: BLE001 - the enable stands; a restart starts DISABLED
            log.error("live.enablement.snapshot_not_persisted", error=type(exc).__name__)
    return EnableOutcome(enabled=True, reason=REASON_ENABLED, persisted=persisted)


def _refusal(
    verdict: HealthVerdict, kill_gate_state: KillGateState | None
) -> tuple[str, tuple[str, ...]] | None:
    if verdict.mode is not HealthRuntimeMode.DEMO:
        return REASON_VERDICT_NOT_FOR_DEMO, ()
    if verdict.is_no_trade:
        return REASON_HEALTH_NOT_OK, _failing_names(verdict)
    if not isinstance(kill_gate_state, KillGateState):
        return REASON_KILL_GATE_UNEVALUATED, ()
    if kill_gate_state is KillGateState.INSUFFICIENT_EDGE:
        return REASON_KILL_GATE_INSUFFICIENT_EDGE, ()
    return None


# --------------------------------------------------------------------------- #
# Kill gate: only ever toward disabled.
# --------------------------------------------------------------------------- #


async def on_kill_gate_verdict(
    *,
    controller: LiveEnablementController,
    state: KillGateState | None,
    now_utc: datetime,
    persist: Persist | None = None,
) -> KillGateOutcome:
    """Disable once on INSUFFICIENT_EDGE; any other state (or none) changes nothing.

    The disable is journaled by the controller (spill when the journal is down). This function
    never calls `enable`, whatever the state is (T-24-67).
    """
    if state is not KillGateState.INSUFFICIENT_EDGE:
        return KillGateOutcome(action=ACTION_NO_CHANGE, state=state)
    if controller.is_disabled:
        return KillGateOutcome(action=ACTION_ALREADY_DISABLED, state=state)
    controller.disable(operator_id=KILL_GATE_OPERATOR_ID, now_utc=now_utc)
    log.warning("live.enablement.kill_gate_disabled")
    if persist is not None:
        try:
            await persist()
        except Exception as exc:  # noqa: BLE001 - the controller is already disabled
            log.error("live.enablement.snapshot_not_persisted", error=type(exc).__name__)
    return KillGateOutcome(action=ACTION_DISABLED, state=state)


async def kill_gate_tick_once(
    *,
    controller: LiveEnablementController,
    source: KillGateSource,
    now_utc: datetime,
    persist: Persist | None = None,
) -> KillGateOutcome:
    """The scheduler body (cadence: the health tick): read the analytics state, act toward off."""
    return await on_kill_gate_verdict(
        controller=controller, state=await source(), now_utc=now_utc, persist=persist
    )


__all__ = [
    "ACTION_ALREADY_DISABLED",
    "ACTION_DISABLED",
    "ACTION_NO_CHANGE",
    "DEMO_RUNTIME_OPERATOR_ID",
    "EVENT_ENABLEMENT_RESET_AT_START",
    "EVENT_ENABLE_REFUSED",
    "KILL_GATE_OPERATOR_ID",
    "REASON_ALREADY_ENABLED",
    "REASON_ENABLED",
    "REASON_HEALTH_NOT_OK",
    "REASON_KILL_GATE_INSUFFICIENT_EDGE",
    "REASON_KILL_GATE_UNEVALUATED",
    "REASON_VERDICT_NOT_FOR_DEMO",
    "EnableOutcome",
    "KillGateOutcome",
    "KillGateSource",
    "LiveEnableForbidden",
    "StartEnablement",
    "SystemStateStore",
    "enable_demo",
    "kill_gate_tick_once",
    "on_kill_gate_verdict",
    "persist_enablement_snapshot",
    "start_disabled",
]
