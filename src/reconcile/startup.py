"""Startup recovery: rebuild every safety-relevant state from durable sources (Phase 20, 20-19).

``run_startup_recovery`` runs once per process start, before the first reconcile or protection
tick, in a fixed order (D-30, D-08):

1. load SAFE_MODE (``safe_mode_load``; an unreadable store starts the controller IN SAFE_MODE with
   ``SAFE_MODE_STATE_UNREADABLE`` and recovery continues, because monitoring must);
2. load the open pending protective actions (an unreadable store enters SAFE_MODE ``DB_FAILURE``);
3. read the local spill once (a missing directory is "nothing pending"; an unreadable spill or a
   corrupt entry enters SAFE_MODE ``RESTORE_INCONSISTENT`` and the plans' spill rows become None,
   so a stop history that depended on it is UNKNOWN);
4. rebuild the coordinator (``restored_plans_builder`` -> ``coordinator.restore``) and the closer
   (``close_attempts_reader`` plus the spill -> ``closer.restore_pending``). A builder that
   raises ``PartialRestore`` rebuilt the healthy plans but not every entry: the healthy plans are
   restored (they stay supervised), then the step fails with SAFE_MODE ``RESTORE_INCONSISTENT``;
   any other builder exception still restores nothing and enters ``DB_FAILURE``;
5. ``resolve_unresolved_intents`` (AFTER the rebuild, so a live plan's protective legs stay
   UNKNOWN for the coordinator to place or confirm, research F5);
6. replay the spill into the journal (a conflict or a corrupt file enters SAFE_MODE
   ``RESTORE_INCONSISTENT``, a failed write ``DB_FAILURE``; files are kept).

Rules this module keeps:

* No source is trusted over Binance. It reads only through the injected probes and the
  coordinator's and closer's later ticks; it places, cancels and closes nothing, and the probe
  adapter type has no placement method.
* SAFE_MODE exit stays manual (D-15): this module never calls ``exit_safe_mode``.
* Every guarded step fails closed: an unreadable, missing-but-required, corrupt or conflicting
  source enters SAFE_MODE and the next steps still run. A SAFE_MODE controller that cannot persist
  the entry keeps its in-memory flag; the failure is named in ``StartupReport.safe_mode_errors``
  (exception class names only, never text).
* Inputs that need persistence (journal reads, plan builders, the pending store) are injected
  callables or Protocol-typed objects, so this module imports no ``src.persistence`` module. The
  default spill replay is imported lazily, so the reconcile package keeps no dependency on the
  data layer.
* The first tick is the composition's call (Phase 24); wiring a running process is NOT claimed.

Evidence label: executed tests with fakes; no ``[DEMO]`` claim.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from src.domain.journal import JournalEvent
from src.execution.emergency_close import (
    EVENT_EMERGENCY_CLOSE,
    RestoredAttempt,
    pending_attempts_from_events,
    plan_hash_of_close_event,
)
from src.execution.intent_recovery import IntentProbeAdapter, RecoveryReport
from src.execution.intent_recovery import resolve_unresolved_intents as _resolve_intents
from src.execution.intent_store import ExecutionIntentStore
from src.execution.pending_actions import PendingAction, PendingActionStore
from src.execution.protection import (
    SAFE_MODE_DB_FAILURE,
    SAFE_MODE_RESTORE_INCONSISTENT,
    RestoreReport,
)

if TYPE_CHECKING:
    from src.execution.protection_rebuild import RestoredPlan

# The fixed order of the steps (``StartupReport.steps``).
STEP_SAFE_MODE_LOADED = "SAFE_MODE_LOADED"
STEP_PENDING_LOADED = "PENDING_LOADED"
STEP_SPILL_READ = "SPILL_READ"
STEP_COORDINATOR_RESTORED = "COORDINATOR_RESTORED"
STEP_CLOSER_RESTORED = "CLOSER_RESTORED"
STEP_INTENTS_RESOLVED = "INTENTS_RESOLVED"
STEP_SPILL_REPLAYED = "SPILL_REPLAYED"

_PROTECTION_CORRELATION_PREFIX = "protection_"


class SafeModeLike(Protocol):
    """The two things startup asks of the SAFE_MODE controller (never ``exit_safe_mode``)."""

    @property
    def in_safe_mode(self) -> bool: ...

    def enter_safe_mode(self, *, reason: str, now_utc: datetime | None = None) -> None: ...


class RestorableCoordinator(Protocol):
    """What startup calls on the ``ProtectionCoordinator``."""

    @property
    def restore_complete(self) -> bool: ...

    def restore(self, plans: Sequence[Any], *, now_utc: datetime) -> RestoreReport: ...


class RestorableCloser(Protocol):
    """What startup calls on the ``MarketEmergencyCloser``."""

    def restore_pending(self, *, plan_hash: str, attempts: Sequence[RestoredAttempt]) -> None: ...


class SpillReader(Protocol):
    """The read side of ``src.ops.spill.LocalSpill`` startup uses (one scan)."""

    def scan(self) -> Any: ...


type SpillRowsFor = Callable[[str], Sequence[JournalEvent] | None]
type PlansBuilder = Callable[[SpillRowsFor], Sequence[RestoredPlan]]


class PartialRestore(Exception):  # noqa: N818 - a partial result, not an error to the caller
    """A plans builder rebuilt the healthy plans but could not rebuild `unrestorable` others.

    Raised by a `PlansBuilder` after its client-id index holds the healthy plans. Recovery
    restores `plans` (they stay supervised), then fails COORDINATOR_RESTORED with SAFE_MODE
    `RESTORE_INCONSISTENT`. The message carries the count only, never row text.
    """

    def __init__(self, plans: Sequence[RestoredPlan], unrestorable: int) -> None:
        super().__init__(f"{unrestorable} restorable entries could not be rebuilt")
        self.plans: tuple[RestoredPlan, ...] = tuple(plans)
        self.unrestorable = unrestorable


type CloseAttemptsReader = Callable[[], Mapping[str, Sequence[JournalEvent]]]
type SpillReplay = Callable[[Any, Any], Any]


@dataclass(frozen=True)
class StartupReport:
    """What one recovery pass did. Names, counts and reason codes only; never row text.

    ``steps`` lists the steps that ran to completion in order; ``failed_steps`` the ones that did
    not (they entered SAFE_MODE; later steps still ran). ``safe_mode_reasons`` are the reasons
    startup itself entered; the reasons the coordinator, the closer or intent recovery entered
    are in their own reports.
    """

    steps: tuple[str, ...]
    failed_steps: tuple[str, ...]
    safe_mode_reasons: tuple[str, ...]
    safe_mode_errors: tuple[str, ...]
    in_safe_mode: bool
    pending_open: int | None
    spill_records: int
    spill_corrupt: tuple[tuple[str, str], ...]
    plans_restored: int
    restore_report: RestoreReport | None
    restore_complete: bool
    close_attempts_adopted: tuple[tuple[str, int], ...]
    intents: RecoveryReport | None
    spill_replay: Any
    plans_unrestorable: int = 0


class _Run:
    """Mutable bookkeeping of one pass (kept out of the public report)."""

    def __init__(self, controller: SafeModeLike, now_utc: datetime) -> None:
        self.controller = controller
        self.now_utc = now_utc
        self.steps: list[str] = []
        self.failed: list[str] = []
        self.reasons: list[str] = []
        self.errors: list[str] = []

    def enter(self, reason: str) -> None:
        """Enter SAFE_MODE, fail closed: a controller error is named, never raised."""
        if reason not in self.reasons:
            self.reasons.append(reason)
        try:
            self.controller.enter_safe_mode(reason=reason, now_utc=self.now_utc)
        except Exception as exc:  # noqa: BLE001 - the flag flips before the save; name the class
            self.errors.append(type(exc).__name__)

    def ok(self, step: str) -> None:
        self.steps.append(step)

    def fail(self, step: str, reason: str) -> None:
        self.failed.append(step)
        self.enter(reason)


def _scan_spill(
    spill: SpillReader | None,
) -> tuple[bool, tuple[JournalEvent, ...], tuple[Any, ...]]:
    """(readable, the spilled events, the corrupt entries). No spill means nothing pending."""
    if spill is None:
        return True, (), ()
    try:
        scan = spill.scan()
        events = tuple(record.event for record in scan.records)
        corrupt = tuple(scan.corrupt)
    except Exception:  # noqa: BLE001 - an unreadable spill proves nothing: handled by the caller
        return False, (), ()
    return True, events, corrupt


def _close_events_by_plan(
    journal_events: Mapping[str, Sequence[JournalEvent]] | None,
    spilled: Sequence[JournalEvent],
) -> dict[str, list[JournalEvent]]:
    """EMERGENCY_CLOSE events per plan from the journal and the spill, one copy per event id."""
    merged: dict[str, dict[str, JournalEvent]] = {}
    for plan_hash, events in (journal_events or {}).items():
        for event in events:
            merged.setdefault(plan_hash, {})[event.journal_event_id] = event
    for event in spilled:
        if event.event_type != EVENT_EMERGENCY_CLOSE:
            continue
        spilled_plan = plan_hash_of_close_event(event)
        if spilled_plan is not None:
            merged.setdefault(spilled_plan, {}).setdefault(event.journal_event_id, event)
    return {plan: list(events.values()) for plan, events in merged.items()}


async def run_startup_recovery(
    *,
    safe_mode_load: Callable[[], SafeModeLike],
    pending_store: PendingActionStore,
    coordinator: RestorableCoordinator,
    closer: RestorableCloser,
    restored_plans_builder: PlansBuilder,
    close_attempts_reader: CloseAttemptsReader,
    intent_store: ExecutionIntentStore,
    probe_adapter: IntentProbeAdapter,
    journal: Any,
    spill: SpillReader | None,
    now_utc: datetime,
    spill_replay: SpillReplay | None = None,
) -> StartupReport:
    """Run the fixed startup order once; see the module docstring.

    Args:
        safe_mode_load: returns the SAFE_MODE controller already loaded from its durable store
            (``SafeModeController.load``, which never raises for a store failure). It must be the
            controller the coordinator and the closer were built with.
        pending_store: the durable pending-action store (``list_open`` is read once).
        coordinator: a ``ProtectionCoordinator`` built with ``restore_required=True``.
        closer: the ``MarketEmergencyCloser``.
        restored_plans_builder: called with ``spill_rows_for(plan_hash)`` (the spill's records of
            that plan's protection correlation, or None when the spill is unreadable or corrupt);
            returns the ``RestoredPlan`` list built with ``protection_rebuild.rebuild_plan``. It
            reads the journal, the intent rows and the persisted plans (Phase 24 wiring).
        close_attempts_reader: the journal's ``EMERGENCY_CLOSE`` events grouped by plan hash.
        intent_store: the execution-intent store ``resolve_unresolved_intents`` works on.
        probe_adapter: the read-only probe adapter (no placement method exists on its type).
        journal: the journal the spill is replayed into.
        spill: the local spill (``LocalSpill``), or None when none is configured.
        now_utc: the injected UTC clock reading (no wall clock is read here).
        spill_replay: replaces ``src.ops.spill.replay_spill`` (tests).

    Returns:
        A ``StartupReport``. Nothing in it is trusted over Binance.
    """
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise ValueError("now_utc must be a timezone-aware datetime")
    controller = safe_mode_load()
    run = _Run(controller, now_utc)
    run.ok(STEP_SAFE_MODE_LOADED)

    # 2. open pending actions
    pending_open: int | None = None
    try:
        open_actions: tuple[PendingAction, ...] = tuple(pending_store.list_open())
        pending_open = len(open_actions)
        run.ok(STEP_PENDING_LOADED)
    except Exception:  # noqa: BLE001 - an unreadable store is not "nothing pending"
        run.fail(STEP_PENDING_LOADED, SAFE_MODE_DB_FAILURE)

    # 3. the spill, read once
    readable, spilled, corrupt = _scan_spill(spill)
    spill_ok = readable and not corrupt
    if spill_ok:
        run.ok(STEP_SPILL_READ)
    else:
        run.fail(STEP_SPILL_READ, SAFE_MODE_RESTORE_INCONSISTENT)

    def spill_rows_for(plan_hash: str) -> Sequence[JournalEvent] | None:
        if not spill_ok:
            return None
        correlation = f"{_PROTECTION_CORRELATION_PREFIX}{plan_hash}"
        return [event for event in spilled if event.correlation_id == correlation]

    # 4a. the coordinator
    restore_report: RestoreReport | None = None
    plans_restored = 0
    plans_unrestorable = 0
    try:
        plans = restored_plans_builder(spill_rows_for)
    except PartialRestore as partial:
        # The healthy plans stay supervised; the unrestorable ones fail the step closed.
        plans_unrestorable = partial.unrestorable
        try:
            restore_report = coordinator.restore(partial.plans, now_utc=now_utc)
            plans_restored = len(restore_report.restored)
        except Exception:  # noqa: BLE001 - a refused restore leaves restore_complete False
            pass
        run.fail(STEP_COORDINATOR_RESTORED, SAFE_MODE_RESTORE_INCONSISTENT)
    except Exception:  # noqa: BLE001 - the plans cannot be read: nothing is restored, entries stay blocked
        run.fail(STEP_COORDINATOR_RESTORED, SAFE_MODE_DB_FAILURE)
    else:
        try:
            restore_report = coordinator.restore(plans, now_utc=now_utc)
            plans_restored = len(restore_report.restored)
            run.ok(STEP_COORDINATOR_RESTORED)
        except Exception:  # noqa: BLE001 - a refused restore leaves restore_complete False
            run.fail(STEP_COORDINATOR_RESTORED, SAFE_MODE_RESTORE_INCONSISTENT)

    # 4b. the closer's pending attempts
    adopted: list[tuple[str, int]] = []
    journal_close_events: Mapping[str, Sequence[JournalEvent]] | None = None
    closer_ok = True
    try:
        journal_close_events = close_attempts_reader()
    except Exception:  # noqa: BLE001 - the spill alone may still hold the pre_send row
        closer_ok = False
        run.enter(SAFE_MODE_DB_FAILURE)
    for plan_hash, events in sorted(_close_events_by_plan(journal_close_events, spilled).items()):
        try:
            attempts = pending_attempts_from_events(events)
            closer.restore_pending(plan_hash=plan_hash, attempts=attempts)
        except Exception:  # noqa: BLE001 - a malformed row must not be dropped silently
            closer_ok = False
            run.enter(SAFE_MODE_RESTORE_INCONSISTENT)
            continue
        if attempts:
            adopted.append((plan_hash, max(a.attempt_no for a in attempts)))
    if closer_ok:
        run.ok(STEP_CLOSER_RESTORED)
    else:
        run.failed.append(STEP_CLOSER_RESTORED)

    # 5. intents (after the rebuild: a live plan's protective legs stay UNKNOWN, F5)
    intents: RecoveryReport | None = None
    try:
        intents = await _resolve_intents(
            store=intent_store,
            adapter=probe_adapter,
            safe_mode_controller=controller,
            now_utc=now_utc,
        )
        run.ok(STEP_INTENTS_RESOLVED)
    except Exception:  # noqa: BLE001 - recovery already entered DB_FAILURE for a store error
        run.fail(STEP_INTENTS_RESOLVED, SAFE_MODE_DB_FAILURE)

    # 6. replay the spill into the journal (files that conflict or are corrupt are kept)
    replay_report: Any = None
    if spill is not None and not readable:
        # An unreadable spill cannot be replayed; the files stay where they are (CR-C1).
        run.fail(STEP_SPILL_REPLAYED, SAFE_MODE_RESTORE_INCONSISTENT)
    elif spill is not None:
        try:
            replay = spill_replay if spill_replay is not None else _default_replay()
            replay_report = replay(spill, journal)
        except Exception:  # noqa: BLE001 - the journal cannot take the spill
            run.fail(STEP_SPILL_REPLAYED, SAFE_MODE_DB_FAILURE)
        else:
            if getattr(replay_report, "conflicts", ()) or getattr(replay_report, "corrupt", ()):
                run.fail(STEP_SPILL_REPLAYED, SAFE_MODE_RESTORE_INCONSISTENT)
            elif getattr(replay_report, "failed", ()):
                run.fail(STEP_SPILL_REPLAYED, SAFE_MODE_DB_FAILURE)
            else:
                run.ok(STEP_SPILL_REPLAYED)
    else:
        run.ok(STEP_SPILL_REPLAYED)

    return StartupReport(
        steps=tuple(run.steps),
        failed_steps=tuple(run.failed),
        safe_mode_reasons=tuple(run.reasons),
        safe_mode_errors=tuple(run.errors),
        in_safe_mode=controller.in_safe_mode,
        pending_open=pending_open,
        spill_records=len(spilled),
        spill_corrupt=tuple((str(item[0]), str(item[1])) for item in corrupt),
        plans_restored=plans_restored,
        restore_report=restore_report,
        restore_complete=coordinator.restore_complete,
        close_attempts_adopted=tuple(adopted),
        intents=intents,
        spill_replay=replay_report,
        plans_unrestorable=plans_unrestorable,
    )


def _default_replay() -> SpillReplay:
    """``src.ops.spill.replay_spill``, imported on first use (it pulls in the data layer)."""
    from src.ops.spill import replay_spill

    return replay_spill


__all__ = [
    "STEP_CLOSER_RESTORED",
    "STEP_COORDINATOR_RESTORED",
    "STEP_INTENTS_RESOLVED",
    "STEP_PENDING_LOADED",
    "STEP_SAFE_MODE_LOADED",
    "STEP_SPILL_READ",
    "STEP_SPILL_REPLAYED",
    "RestorableCloser",
    "RestorableCoordinator",
    "CloseAttemptsReader",
    "PartialRestore",
    "PlansBuilder",
    "SafeModeLike",
    "SpillReader",
    "SpillReplay",
    "SpillRowsFor",
    "StartupReport",
    "run_startup_recovery",
]
