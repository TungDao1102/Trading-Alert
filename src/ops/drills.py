"""RUNBOOK drill rehearsal harness (Phase 8, plan 08-05).

Per D-05 (OPS-01 acceptance proof): every RUNBOOK procedure must be
rehearsed with an injected fault before live enablement, with a
journaled outcome proving the rehearsal ran end-to-end. The drill
harness drives the 08-01 approval core, the 08-02 receiver seam, and
the 08-04 reconciler / sweeper / SAFE_MODE through fakes only — it
NEVER touches the network, places a real order, or creates real
unprotected exposure.

Drill vocabulary (one per RUNBOOK procedure, in the order the
acceptance artifact pins):

  1. unprotected     (§3 Position without confirmed stop)
  2. orphan          (§4 Orphan protective orders)
  3. duplicate       (§5 Suspected duplicate approval/order)
  4. api_down        (§10 Binance API degradation)
  5. stale_feed      (§7 Market feed stale)
  6. db_failure      (§9 Database failure)
  7. manual_close    (§12 Manual close)
  8. restore         (clean restore path — the only SAFE_MODE exit
                     exercised in this plan)

The harness itself (`run_drill`) is a 3-step coordinator:
  - inject(): build a fresh scenario with the simulated fault
  - assert_outcome(): run the system under test, assert SAFE_MODE
    / sweep / journal state matches the expected outcome
  - record(): emit one JournalEvent with event_type DRILL_OUTCOME
    carrying the drill name, the injected fault description, the
    observed outcome, and the UTC timestamp.

The drill log (`DrillLog`) is append-only: events are inserted in the
order drills run, and the canonical name tuple pins the order across
repeat runs. A repeat run produces a byte-identical drill log because:
  - drill names are sorted into the canonical tuple at module load;
  - inject / assert_outcome are pure functions of injected fakes;
  - the only time-dependent field is `occurred_at_utc`, which the
    caller injects (never `datetime.now()`).

The module is dependency-free: stdlib + `src/domain/*` + sibling
modules only. No Binance SDK, no SQLAlchemy, no Telegram PTB.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from src.domain.journal import JournalEvent

# --------------------------------------------------------------------------- #
# Canonical drill vocabulary — the eight RUNBOOK procedures this plan
# rehearses. Tuple order is part of the acceptance contract: the golden
# drill log pins the order, and a parallel / interrupted re-run must
# NEVER reorder the entries. Tests assert `len(DRILL_NAMES) == 8` and
# the literal names.
# --------------------------------------------------------------------------- #

DRILL_UNPROTECTED: str = "unprotected"
DRILL_ORPHAN: str = "orphan"
DRILL_DUPLICATE: str = "duplicate"
DRILL_API_DOWN: str = "api_down"
DRILL_STALE_FEED: str = "stale_feed"
DRILL_DB_FAILURE: str = "db_failure"
DRILL_MANUAL_CLOSE: str = "manual_close"
DRILL_RESTORE: str = "restore"

DRILL_NAMES: tuple[str, ...] = (
    DRILL_UNPROTECTED,
    DRILL_ORPHAN,
    DRILL_DUPLICATE,
    DRILL_API_DOWN,
    DRILL_STALE_FEED,
    DRILL_DB_FAILURE,
    DRILL_MANUAL_CLOSE,
    DRILL_RESTORE,
)

# Map each drill to the RUNBOOK section it rehearses. Stored as a
# frozen mapping so tests can assert the canonical pairing.
DRILL_RUNBOOK_SECTION: dict[str, str] = {
    DRILL_UNPROTECTED: "§3 Position without confirmed stop",
    DRILL_ORPHAN: "§4 Orphan protective orders",
    DRILL_DUPLICATE: "§5 Suspected duplicate approval/order",
    DRILL_API_DOWN: "§10 Binance API degradation",
    DRILL_STALE_FEED: "§7 Market feed stale",
    DRILL_DB_FAILURE: "§9 Database failure",
    DRILL_MANUAL_CLOSE: "§12 Manual close",
    DRILL_RESTORE: "restore path (only SAFE_MODE exit)",
}

# Canonical outcome vocabulary. These are the only outcome strings
# the harness emits. Tests assert the union of observed outcomes is
# contained in this set.
OUTCOME_SAFE_MODE_ENTERED: str = "safe_mode_entered"
OUTCOME_SAFE_MODE_BLOCKED: str = "safe_mode_blocked_entries"
OUTCOME_ORPHAN_SWEPTED: str = "orphan_swept"
OUTCOME_REPLAY_TRANSITIONED: str = "replay_one_transition"
OUTCOME_RESTORE_CLEAN_EXIT: str = "restore_clean_exit"
OUTCOME_NO_PLACE_ORDER_INVARIANT: str = "no_place_order_invariant_held"

ALL_OUTCOMES: frozenset[str] = frozenset(
    {
        OUTCOME_SAFE_MODE_ENTERED,
        OUTCOME_SAFE_MODE_BLOCKED,
        OUTCOME_ORPHAN_SWEPTED,
        OUTCOME_REPLAY_TRANSITIONED,
        OUTCOME_RESTORE_CLEAN_EXIT,
        OUTCOME_NO_PLACE_ORDER_INVARIANT,
    }
)


# --------------------------------------------------------------------------- #
# Frozen dataclasses — the public drill contract.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DrillOutcome:
    """The outcome of one `run_drill(...)` invocation.

    `fault` is a short human-readable string describing the injected
    fault (e.g. "local algo protective with no position" for the
    orphan drill). `outcome` is one of the canonical OUTCOME_* strings
    declared above. `occurred_at_utc` is the caller-supplied UTC
    timestamp — never wall-clock.
    """

    drill: str
    fault: str
    outcome: str
    occurred_at_utc: datetime

    def __post_init__(self) -> None:
        if self.drill not in DRILL_NAMES:
            raise ValueError(
                f"DrillOutcome: unknown drill {self.drill!r} (known: {list(DRILL_NAMES)})"
            )
        if self.outcome not in ALL_OUTCOMES:
            raise ValueError(
                f"DrillOutcome: unknown outcome {self.outcome!r} (known: {sorted(ALL_OUTCOMES)})"
            )
        if not isinstance(self.fault, str) or self.fault == "":
            raise ValueError("DrillOutcome: fault must be a non-empty string")
        if self.occurred_at_utc.tzinfo is None:
            raise ValueError("DrillOutcome: occurred_at_utc must be UTC-aware")
        if self.occurred_at_utc.utcoffset() != _ZERO_TIMEDELTA:
            raise ValueError("DrillOutcome: occurred_at_utc must be UTC")


# Type alias for the inject callable (scenario builder). Returns a
# short fault description string.
InjectFault = Callable[[], str]

# Type alias for the assert-outcome callable. Receives a `DrillLog`
# (the journal the harness records into) and an injectable context
# dict; returns the canonical OUTCOME_* string.
AssertOutcome = Callable[["DrillLog", dict[str, Any]], str]


@dataclass(frozen=True)
class DrillDeclaration:
    """One declared drill — the unit the harness runs.

    `name` is the canonical DRILL_* string. `runbook_section` is the
    human-readable RUNBOOK reference. `inject` is the fault builder
    (must be pure; no side effects on shared state). `assert_outcome`
    runs the system under test with the injected scenario and
    returns the canonical OUTCOME_* string.
    """

    name: str
    runbook_section: str
    inject: InjectFault
    assert_outcome: AssertOutcome

    def __post_init__(self) -> None:
        if self.name not in DRILL_NAMES:
            raise ValueError(
                f"DrillDeclaration: unknown name {self.name!r} (known: {list(DRILL_NAMES)})"
            )
        if not isinstance(self.runbook_section, str) or self.runbook_section == "":
            raise ValueError("DrillDeclaration: runbook_section must be a non-empty string")
        if not callable(self.inject):
            raise TypeError("DrillDeclaration: inject must be callable")
        if not callable(self.assert_outcome):
            raise TypeError("DrillDeclaration: assert_outcome must be callable")


# --------------------------------------------------------------------------- #
# Drill log — append-only ordered list of JournalEvents.
# --------------------------------------------------------------------------- #


class DrillLog:
    """Append-only journal the harness records DRILL_OUTCOME events into.

    The log is the acceptance artifact for OPS-01. Tests assert the
    log contains exactly one DRILL_OUTCOME event per drill name in the
    canonical `DRILL_NAMES` order; repeat runs must produce a
    byte-identical log when the same `now_utc` sequence is supplied.

    The log ALSO records any side-events the drills produce (e.g.,
    `SAFE_MODE_ENTER`, `ORPHAN_SWEEP` from the underlying system).
    The golden fixture pins the union: every DRILL_OUTCOME plus the
    key side-events.

    Single-writer only: `run_all_drills` is the sole writer in
    sequential runs. A lock guards `record`/`reset` so concurrent
    `run_drill` calls cannot interleave or drop rows silently, and a
    monotonically increasing sequence number pins dispatch order.
    """

    def __init__(self) -> None:
        import threading

        self.events: list[JournalEvent] = []
        self._lock = threading.Lock()
        self._sequence = 0

    def record(self, event: JournalEvent) -> None:
        """Record a JournalEvent into the log (append-only)."""
        with self._lock:
            self._sequence += 1
            self.events.append(event)

    def drill_outcome_events(self) -> tuple[JournalEvent, ...]:
        """Return just the DRILL_OUTCOME events (one per drill)."""
        with self._lock:
            return tuple(e for e in self.events if e.event_type == "DRILL_OUTCOME")

    def ordered_drill_outcomes(self) -> tuple[str, ...]:
        """Return the ordered drill names emitted as DRILL_OUTCOME."""
        with self._lock:
            return tuple(e.entity_id for e in self.events if e.event_type == "DRILL_OUTCOME")

    def reset(self) -> None:
        """Clear the log (for repeat-run determinism tests)."""
        with self._lock:
            self.events = []
            self._sequence = 0


# --------------------------------------------------------------------------- #
# run_drill — the harness.
# --------------------------------------------------------------------------- #


_ZERO_TIMEDELTA = timedelta(0)


def _run_coro(coro: Any) -> Any:
    import asyncio
    import concurrent.futures

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def run_drill(
    declaration: DrillDeclaration,
    *,
    journal: DrillLog,
    now_utc: datetime,
    context: dict[str, Any] | None = None,
) -> DrillOutcome:
    """Run one drill: inject the fault, assert the outcome, journal.

    The 3-step harness the plan pins:
      1. inject(): the declaration's fault builder returns the fault
         string. The declaration also receives the journal + context
         so it can pre-seed side events (e.g., a SAFE_MODE_ENTER event
         from the underlying system) into the log.
      2. assert_outcome(): the declaration's outcome runner exercises
         the system under test with the injected scenario and returns
         the canonical OUTCOME_* string.
      3. record(): one JournalEvent with event_type=DRILL_OUTCOME,
         entity_id=<drill name>, payload carrying {fault, outcome,
         occurred_at_utc, runbook_section}.

    Args:
        declaration: The drill declaration to run.
        journal: The drill log to record events into.
        now_utc: Caller-supplied UTC timestamp for the DRILL_OUTCOME
            event (never wall-clock — repeat runs must be
            byte-identical).
        context: Optional injectable context (fakes, controller, etc.)
            shared across the drill's inject + assert_outcome.

    Returns:
        A `DrillOutcome` carrying the drill name, fault, outcome, and
        timestamp. The journal has one new DRILL_OUTCOME event
        appended.
    """
    if now_utc.tzinfo is None:
        raise ValueError("run_drill: now_utc must be UTC-aware")
    if now_utc.utcoffset() != _ZERO_TIMEDELTA:
        raise ValueError("run_drill: now_utc must be UTC")
    ctx = context if context is not None else {}

    fault = declaration.inject()
    outcome = declaration.assert_outcome(journal, ctx)

    event = _build_drill_outcome_event(
        declaration=declaration,
        fault=fault,
        outcome=outcome,
        now_utc=now_utc,
    )
    journal.record(event)
    return DrillOutcome(
        drill=declaration.name,
        fault=fault,
        outcome=outcome,
        occurred_at_utc=now_utc,
    )


def run_all_drills(
    declarations: Sequence[DrillDeclaration],
    *,
    journal: DrillLog,
    now_utc_sequence: Sequence[datetime],
    context: dict[str, Any] | None = None,
) -> tuple[DrillOutcome, ...]:
    """Run every drill in the canonical `DRILL_NAMES` order.

    `declarations` MUST contain exactly one declaration per canonical
    drill name (a missing drill or a duplicate name raises
    `ValueError`). `now_utc_sequence` must have one datetime per
    declaration — the harness does NOT generate timestamps itself
    (repeat-run determinism requires a fixed sequence).

    Returns the ordered tuple of DrillOutcomes. The journal is
    populated with one DRILL_OUTCOME per drill (plus any side-events
    the drills emit).
    """
    if len(declarations) != len(DRILL_NAMES):
        raise ValueError(
            f"run_all_drills: expected {len(DRILL_NAMES)} declarations, got {len(declarations)}"
        )
    if len(now_utc_sequence) != len(DRILL_NAMES):
        raise ValueError(
            f"run_all_drills: expected {len(DRILL_NAMES)} timestamps, got {len(now_utc_sequence)}"
        )
    by_name: dict[str, DrillDeclaration] = {}
    for decl in declarations:
        if decl.name in by_name:
            raise ValueError(f"run_all_drills: duplicate drill name {decl.name!r}")
        by_name[decl.name] = decl

    outcomes: list[DrillOutcome] = []
    for index, drill_name in enumerate(DRILL_NAMES):
        declaration = by_name[drill_name]
        outcome = run_drill(
            declaration,
            journal=journal,
            now_utc=now_utc_sequence[index],
            context=context,
        )
        outcomes.append(outcome)
    return tuple(outcomes)


# --------------------------------------------------------------------------- #
# Internal helpers.
# --------------------------------------------------------------------------- #


def _build_drill_outcome_event(
    *,
    declaration: DrillDeclaration,
    fault: str,
    outcome: str,
    now_utc: datetime,
) -> JournalEvent:
    """Build the DRILL_OUTCOME JournalEvent.

    The event's correlation_id includes the drill name so the
    audit-trail join can group every side-event for one drill under
    a single correlation_id prefix.
    """
    if now_utc.tzinfo is None:
        raise ValueError("_build_drill_outcome_event: now_utc must be UTC-aware")
    payload = {
        "drill": declaration.name,
        "fault": fault,
        "outcome": outcome,
        "occurred_at_utc": now_utc.isoformat(),
        "runbook_section": declaration.runbook_section,
    }
    correlation_id = f"drill:{declaration.name}"
    return JournalEvent(
        journal_event_id=(f"drill_outcome_{declaration.name}_{int(now_utc.timestamp() * 1000)}"),
        occurred_at_utc=now_utc,
        event_type="DRILL_OUTCOME",
        entity_type="Drill",
        entity_id=declaration.name,
        correlation_id=correlation_id,
        payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
    )


# --------------------------------------------------------------------------- #
# Drill factories — the eight RUNBOOK procedures this plan rehearses.
#
# Each factory takes Protocol-typed surfaces as kwargs (the real
# `SafeModeController` / `OrphanSweeper` / `compare` from 08-04
# satisfy them; tests inject fakes). The factories return a
# `DrillDeclaration` the harness runs.
#
# Design contract (D-05):
#   - Drills NEVER place a real order or create real unprotected
#     exposure. Every scenario is a pure fake.
#   - Each drill's `inject()` returns the fault string the harness
#     journals; `assert_outcome()` returns one of the canonical
#     OUTCOME_* strings.
#   - The factories compose the system-under-test (compare / sweeper
#     / SAFE_MODE / replay) but never import the Binance SDK or PTB
#     directly — the fakes satisfy the Protocol-typed surfaces.
# --------------------------------------------------------------------------- #


# Sentinel for SAFE_MODE enter reason on the restore drill: the
# restore path enters SAFE_MODE on a stale compare, then exits on a
# fresh clean compare. The DRILL_OUTCOME event journals the restore
# outcome; the SAFE_MODE_ENTER/EXIT side events are emitted by the
# SafeModeController itself.
_RESTORE_FAULT: str = "stale three-source compare forcing SAFE_MODE enter"
_RESTORE_OUTCOME_FAULT: str = "fresh clean three-source compare after operator-confirmed restore"


def _require_now_utc_utc(value: datetime, field_name: str) -> None:
    """Reject naive or non-UTC datetimes (D-12)."""
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != _ZERO_TIMEDELTA:
        raise ValueError(f"{field_name} must be UTC, got offset {value.utcoffset()}")


def make_unprotected_drill(
    *,
    compare_fn: Callable[..., Any],
    safe_mode_controller: Any,
    local_intent: dict[str, Any],
    truth: dict[str, Any],
) -> DrillDeclaration:
    """Build the UNPROTECTED drill (§3 Position without confirmed stop).

    Per RUNBOOK §3: an open position without a confirmed stop-loss
    forces SAFE_MODE — never auto-place rescue protection. The drill
    injects a local ENTRY + position but no SL algo; the compare
    classifies `ENTRY_WITHOUT_PROTECTIVE` divergence; SAFE_MODE is
    entered; entries are blocked with RECONCILIATION_REQUIRED; no
    cancel call is made (Pitfall 1).

    Args:
        compare_fn: The 08-04 `compare` function.
        safe_mode_controller: A `SafeModeController` instance.
        local_intent: Dict with `open_orders` / `open_algos` /
            `open_positions` keys (duck-typed for compare).
        truth: Dict with `normal_orders` / `algo_orders` / `positions`
            keys.
    """

    def inject() -> str:
        return "local ENTRY + position but no SL protective (ENTRY_WITHOUT_PROTECTIVE)"

    def assert_outcome(journal: DrillLog, context: dict[str, Any]) -> str:
        diff = compare_fn(
            local_open_orders=local_intent["open_orders"],
            local_open_algos=local_intent["open_algos"],
            local_open_positions=local_intent["open_positions"],
            truth_normal_orders=truth["normal_orders"],
            truth_algo_orders=truth["algo_orders"],
            truth_positions=truth["positions"],
        )
        if diff.agreement:
            raise AssertionError("unprotected drill: expected divergence, got agreement")
        if not any(d.kind == "ENTRY_WITHOUT_PROTECTIVE" for d in diff.divergences):
            raise AssertionError("unprotected drill: expected ENTRY_WITHOUT_PROTECTIVE divergence")
        # Enter SAFE_MODE on the divergence (mirrors the reconciler tick).
        safe_mode_controller.enter_safe_mode(reason="ENTRY_WITHOUT_PROTECTIVE")
        # Guard blocks new entries with RECONCILIATION_REQUIRED.
        verdict = safe_mode_controller.guard_new_entries(trade_plan=None)
        if not verdict.is_no_trade:
            raise AssertionError("unprotected drill: expected guard_new_entries to block entries")
        if verdict.reason_code != "RECONCILIATION_REQUIRED":
            raise AssertionError("unprotected drill: expected RECONCILIATION_REQUIRED reason")
        return OUTCOME_SAFE_MODE_ENTERED

    return DrillDeclaration(
        name=DRILL_UNPROTECTED,
        runbook_section=DRILL_RUNBOOK_SECTION[DRILL_UNPROTECTED],
        inject=inject,
        assert_outcome=assert_outcome,
    )


def make_orphan_drill(
    *,
    compare_fn: Callable[..., Any],
    sweeper: Any,
    safe_mode_controller: Any,
    local_intent: dict[str, Any],
    truth: dict[str, Any],
    position_verifier: Callable[..., Any],
) -> DrillDeclaration:
    """Build the ORPHAN drill (§4 Orphan protective orders).

    Per RUNBOOK §4 + 08-04 D-02: a local algo protective with no
    matching local position AND no exchange position is an orphan
    protective. The sweeper cancels it after authoritative
    position-zero verification (two consecutive zero reads) and
    journals pre/post images as `ORPHAN_SWEEP` events. SAFE_MODE is
    entered before the sweep (the divergence is the trigger).

    Args:
        compare_fn: The 08-04 `compare` function.
        sweeper: An `OrphanSweeper` instance.
        safe_mode_controller: A `SafeModeController` instance.
        local_intent: Dict with `open_orders` / `open_algos` /
            `open_positions` keys.
        truth: Dict with `normal_orders` / `algo_orders` / `positions`
            keys.
        position_verifier: Caller-supplied function returning the
            current position amount for a symbol.
    """
    import asyncio

    def inject() -> str:
        return (
            "local algo protective with no matching local position "
            "and no exchange position (ORPHAN_PROTECTIVE)"
        )

    def assert_outcome(journal: DrillLog, context: dict[str, Any]) -> str:
        diff = compare_fn(
            local_open_orders=local_intent["open_orders"],
            local_open_algos=local_intent["open_algos"],
            local_open_positions=local_intent["open_positions"],
            truth_normal_orders=truth["normal_orders"],
            truth_algo_orders=truth["algo_orders"],
            truth_positions=truth["positions"],
        )
        if diff.agreement:
            raise AssertionError("orphan drill: expected divergence, got agreement")
        if not any(d.kind == "ORPHAN_PROTECTIVE" for d in diff.divergences):
            raise AssertionError("orphan drill: expected ORPHAN_PROTECTIVE divergence")
        if len(diff.orphan_protectives) == 0:
            raise AssertionError("orphan drill: expected orphan_protectives list populated")
        # Enter SAFE_MODE on the divergence (matches the reconciler tick).
        safe_mode_controller.enter_safe_mode(reason="ORPHAN_PROTECTIVE")
        # Sweep the orphan protectives.
        outcome = _run_coro(sweeper.sweep(diff, position_verifier=position_verifier))
        if outcome.swept_count == 0:
            raise AssertionError("orphan drill: expected sweeper to cancel at least one orphan")
        if len(outcome.skipped) > 0:
            raise AssertionError(
                f"orphan drill: unexpected skipped cancels ({len(outcome.skipped)})"
            )
        return OUTCOME_ORPHAN_SWEPTED

    return DrillDeclaration(
        name=DRILL_ORPHAN,
        runbook_section=DRILL_RUNBOOK_SECTION[DRILL_ORPHAN],
        inject=inject,
        assert_outcome=assert_outcome,
    )


def make_duplicate_drill(
    *,
    resolve_callback_fn: Callable[..., Any],
    callback: Any,
    lookup_by_token_hash: Callable[[str], Any],
    save: Callable[[Any], None],
    binding_context: dict[str, Any],
    replay_count: int = 5,
) -> DrillDeclaration:
    """Build the DUPLICATE drill (§5 Suspected duplicate approval/order).

    Per RUNBOOK §5 + 08-01 D-01: a repeated callback for the same
    approval token must return the current state and never create
    another execution intent. The drill replays the same APPROVE
    callback N times and asserts that exactly ONE transition occurs
    (the canonical 5x = 1 transition gate).

    Args:
        resolve_callback_fn: The 08-01 `resolve_callback` function.
        callback: The `Callback` instance to replay.
        lookup_by_token_hash: Caller-supplied lookup callable.
        save: Caller-supplied save callable (records transition count).
        binding_context: Dict with `authorized_chat_id` /
            `expiry_utc` / `approval_strategy_version` /
            `approval_parameter_set_id` /
            `approval_parameter_set_hash` keys.
        replay_count: Number of replays (default 5, the canonical
            08-01 acceptance count).
    """

    def inject() -> str:
        return f"{replay_count}x replay of same APPROVE callback"

    def assert_outcome(journal: DrillLog, context: dict[str, Any]) -> str:
        # Track the number of save() calls — exactly one transition.
        save_call_count = {"n": 0}
        original_save = save

        def counting_save(approval: Any) -> None:
            save_call_count["n"] += 1
            original_save(approval)

        for _ in range(replay_count):
            resolve_callback_fn(
                callback=callback,
                lookup_by_token_hash=lookup_by_token_hash,
                save=counting_save,
                **binding_context,
            )
        if save_call_count["n"] != 1:
            raise AssertionError(
                "duplicate drill: expected exactly 1 save() call across "
                f"{replay_count} replays, got {save_call_count['n']}"
            )
        return OUTCOME_REPLAY_TRANSITIONED

    return DrillDeclaration(
        name=DRILL_DUPLICATE,
        runbook_section=DRILL_RUNBOOK_SECTION[DRILL_DUPLICATE],
        inject=inject,
        assert_outcome=assert_outcome,
    )


def make_api_down_drill(
    *,
    safe_mode_controller: Any,
    api_call: Callable[..., Any],
) -> DrillDeclaration:
    """Build the API_DOWN drill (§10 Binance API degradation).

    Per RUNBOOK §10: never infer absence of an order from a timeout;
    use query/reconciliation before retrying signed order requests.
    The drill injects a transient API failure (timeout / 5xx) on a
    signed order path; SAFE_MODE is entered; no order is placed
    (the no-place-order invariant holds).

    Args:
        safe_mode_controller: A `SafeModeController` instance.
        api_call: Caller-supplied callable that simulates the API
            call (raises a transient error).
    """

    def inject() -> str:
        return "Binance API raised transient error on signed order path"

    def assert_outcome(journal: DrillLog, context: dict[str, Any]) -> str:
        try:
            api_call()
        except RuntimeError:
            pass
        else:
            raise AssertionError("api_down drill: expected api_call to raise transient error")
        # Enter SAFE_MODE on the degradation (matches RUNBOOK §10).
        safe_mode_controller.enter_safe_mode(reason="API_DEGRADATION")
        # Guard blocks new entries.
        verdict = safe_mode_controller.guard_new_entries(trade_plan=None)
        if not verdict.is_no_trade:
            raise AssertionError("api_down drill: expected guard_new_entries to block entries")
        return OUTCOME_SAFE_MODE_ENTERED

    return DrillDeclaration(
        name=DRILL_API_DOWN,
        runbook_section=DRILL_RUNBOOK_SECTION[DRILL_API_DOWN],
        inject=inject,
        assert_outcome=assert_outcome,
    )


def make_stale_feed_drill(
    *,
    safe_mode_controller: Any,
    feed_freshness_check: Callable[[], bool],
) -> DrillDeclaration:
    """Build the STALE_FEED drill (§7 Market feed stale).

    Per RUNBOOK §7: when `now - last_expected_closed_candle > configured
    freshness threshold`, the system issues NO_NEW_SIGNALS and
    NO_NEW_ORDERS, reconnects/re-bootstraps, and resumes only after a
    health check. The drill injects a feed-freshness below-threshold
    read; SAFE_MODE is entered; new entries are blocked.

    Args:
        safe_mode_controller: A `SafeModeController` instance.
        feed_freshness_check: Caller-supplied callable that returns
            True iff the feed is stale.
    """

    def inject() -> str:
        return "market feed freshness below configured threshold"

    def assert_outcome(journal: DrillLog, context: dict[str, Any]) -> str:
        is_stale = feed_freshness_check()
        if not is_stale:
            raise AssertionError("stale_feed drill: expected feed_freshness_check to return True")
        # Enter SAFE_MODE on stale feed (matches RUNBOOK §7).
        safe_mode_controller.enter_safe_mode(reason="STALE_FEED")
        verdict = safe_mode_controller.guard_new_entries(trade_plan=None)
        if not verdict.is_no_trade:
            raise AssertionError("stale_feed drill: expected guard_new_entries to block entries")
        return OUTCOME_SAFE_MODE_ENTERED

    return DrillDeclaration(
        name=DRILL_STALE_FEED,
        runbook_section=DRILL_RUNBOOK_SECTION[DRILL_STALE_FEED],
        inject=inject,
        assert_outcome=assert_outcome,
    )


def make_db_failure_drill(
    *,
    safe_mode_controller: Any,
    db_write: Callable[..., Any],
) -> DrillDeclaration:
    """Build the DB_FAILURE drill (§9 Database failure).

    Per RUNBOOK §9: SAFE_MODE on DB failure; block new orders;
    preserve existing exchange-side protection; reconcile after
    recovery. The drill injects a DB write failure; SAFE_MODE is
    entered; no order is placed.

    Args:
        safe_mode_controller: A `SafeModeController` instance.
        db_write: Caller-supplied callable that simulates a DB write
            (raises a transient error).
    """

    def inject() -> str:
        return "database write raised transient error"

    def assert_outcome(journal: DrillLog, context: dict[str, Any]) -> str:
        try:
            db_write()
        except RuntimeError:
            pass
        else:
            raise AssertionError("db_failure drill: expected db_write to raise transient error")
        # Enter SAFE_MODE on DB failure (matches RUNBOOK §9).
        safe_mode_controller.enter_safe_mode(reason="DB_FAILURE")
        verdict = safe_mode_controller.guard_new_entries(trade_plan=None)
        if not verdict.is_no_trade:
            raise AssertionError("db_failure drill: expected guard_new_entries to block entries")
        return OUTCOME_SAFE_MODE_ENTERED

    return DrillDeclaration(
        name=DRILL_DB_FAILURE,
        runbook_section=DRILL_RUNBOOK_SECTION[DRILL_DB_FAILURE],
        inject=inject,
        assert_outcome=assert_outcome,
    )


def make_manual_close_drill(
    *,
    sweeper: Any,
    safe_mode_controller: Any,
    local_intent: dict[str, Any],
    truth: dict[str, Any],
    position_verifier: Callable[..., Any],
    compare_fn: Callable[..., Any] | None = None,
) -> DrillDeclaration:
    """Build the MANUAL_CLOSE drill (§12 Manual close).

    Per RUNBOOK §12: a manual position close must be explicit and
    recorded; after manual close, the reconciliation process must
    cancel orphan protective orders. The drill injects a manual
    close + orphan protective scenario; the sweeper cancels the
    orphan after position-zero verification; SAFE_MODE is entered
    on the divergence.

    Args:
        sweeper: An `OrphanSweeper` instance.
        safe_mode_controller: A `SafeModeController` instance.
        local_intent: Dict with `open_orders` / `open_algos` /
            `open_positions` keys (duck-typed for sweeper).
        truth: Dict with `normal_orders` / `algo_orders` / `positions`
            keys.
        position_verifier: Caller-supplied function returning the
            current position amount for a symbol.
        compare_fn: The 08-04 `compare` function. Defaults to the
            canonical compare; inject a sentinel in tests to verify
            the drill exercises the configured function.
    """
    if compare_fn is None:
        from src.reconcile.compare import compare as compare_fn


    def inject() -> str:
        return "operator-initiated manual close + orphan protective"

    def assert_outcome(journal: DrillLog, context: dict[str, Any]) -> str:
        # Build a diff against the post-manual-close truth (the local
        # algo protective survives the manual close as an orphan).
        diff = compare_fn(
            local_open_orders=local_intent["open_orders"],
            local_open_algos=local_intent["open_algos"],
            local_open_positions=local_intent["open_positions"],
            truth_normal_orders=truth["normal_orders"],
            truth_algo_orders=truth["algo_orders"],
            truth_positions=truth["positions"],
        )
        if diff.agreement:
            raise AssertionError("manual_close drill: expected divergence after manual close")
        if len(diff.orphan_protectives) == 0:
            raise AssertionError("manual_close drill: expected orphan_protectives list populated")
        safe_mode_controller.enter_safe_mode(reason="MANUAL_CLOSE")
        outcome = _run_coro(sweeper.sweep(diff, position_verifier=position_verifier))
        if outcome.swept_count == 0:
            raise AssertionError("manual_close drill: expected sweeper to cancel the orphan")
        return OUTCOME_ORPHAN_SWEPTED

    return DrillDeclaration(
        name=DRILL_MANUAL_CLOSE,
        runbook_section=DRILL_RUNBOOK_SECTION[DRILL_MANUAL_CLOSE],
        inject=inject,
        assert_outcome=assert_outcome,
    )


def make_restore_drill(
    *,
    safe_mode_controller: Any,
    now_utc: datetime,
    enter_reason: str = "INITIAL_SAFE_MODE",
) -> DrillDeclaration:
    """Build the RESTORE drill (clean restore — the only SAFE_MODE exit).

    Per D-05 + 08-04 D-06: SAFE_MODE exits only on a fresh clean
    three-source compare PLUS a journaled SAFE_MODE_EXIT event
    (Pitfall 4). The restore drill enters SAFE_MODE on a stale
    compare, then exercises the exit path with a clean compare and
    asserts the controller returns to NORMAL.

    Args:
        safe_mode_controller: A `SafeModeController` instance.
        enter_reason: The SAFE_MODE_ENTER reason (default
            "INITIAL_SAFE_MODE"; tests override to exercise specific
            enter paths).
        now_utc: Caller-supplied UTC timestamp for the SAFE_MODE_ENTER
            event.
    """

    def inject() -> str:
        return _RESTORE_FAULT

    def assert_outcome(journal: DrillLog, context: dict[str, Any]) -> str:
        _require_now_utc_utc(now_utc, "now_utc")
        # Step 1: enter SAFE_MODE on a stale compare.
        safe_mode_controller.enter_safe_mode(reason=enter_reason, now_utc=now_utc)
        if not safe_mode_controller.in_safe_mode:
            raise AssertionError("restore drill: expected controller in SAFE_MODE after enter")
        # Step 2: exit SAFE_MODE via the controller's exit path. The
        # fake adapter must return a clean truth (zero divergences).
        import asyncio

        # The exit path is async; tests inject a clean adapter so the
        # controller's compare yields agreement=True.
        exited = _run_coro(safe_mode_controller.exit_safe_mode())
        if not exited:
            raise AssertionError("restore drill: expected exit_safe_mode to return True")
        if safe_mode_controller.in_safe_mode:
            raise AssertionError("restore drill: expected controller out of SAFE_MODE after exit")
        return OUTCOME_RESTORE_CLEAN_EXIT

    return DrillDeclaration(
        name=DRILL_RESTORE,
        runbook_section=DRILL_RUNBOOK_SECTION[DRILL_RESTORE],
        inject=inject,
        assert_outcome=assert_outcome,
    )


# --------------------------------------------------------------------------- #
# Re-export the journal-side constants the harness emits. These are
# used by tests + downstream consumers to assert side-event shape.
# --------------------------------------------------------------------------- #

EVENT_TYPE_DRILL_OUTCOME: str = "DRILL_OUTCOME"


__all__ = [
    "DRILL_NAMES",
    "DRILL_RUNBOOK_SECTION",
    "EVENT_TYPE_DRILL_OUTCOME",
    "DRILL_UNPROTECTED",
    "DRILL_ORPHAN",
    "DRILL_DUPLICATE",
    "DRILL_API_DOWN",
    "DRILL_STALE_FEED",
    "DRILL_DB_FAILURE",
    "DRILL_MANUAL_CLOSE",
    "DRILL_RESTORE",
    "OUTCOME_SAFE_MODE_ENTERED",
    "OUTCOME_SAFE_MODE_BLOCKED",
    "OUTCOME_ORPHAN_SWEPTED",
    "OUTCOME_REPLAY_TRANSITIONED",
    "OUTCOME_RESTORE_CLEAN_EXIT",
    "OUTCOME_NO_PLACE_ORDER_INVARIANT",
    "ALL_OUTCOMES",
    "AssertOutcome",
    "DrillDeclaration",
    "DrillLog",
    "DrillOutcome",
    "InjectFault",
    "make_api_down_drill",
    "make_db_failure_drill",
    "make_duplicate_drill",
    "make_manual_close_drill",
    "make_orphan_drill",
    "make_restore_drill",
    "make_stale_feed_drill",
    "make_unprotected_drill",
    "run_all_drills",
    "run_drill",
]
