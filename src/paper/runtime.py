"""The paper process entrypoint: `python -m src.paper.runtime` (plan 16-22, D-01, L-05, D061 E).

Order of `main` (each step may end the process before the next one runs):

1. Configure redacted logging.
2. Trade-key refusal: any `BINANCE_*` name in the environment exits 3 (names only are printed).
3. Start gate: the approved allowlist is read through the freeze accessors only. An empty
   allowlist logs "SKIPPED (allowlist empty)" before any adapter, database engine or Telegram
   application is constructed, and with no fallback to any set. Without `--hold-on-refusal` it
   exits 0; with the flag it holds like a refusal (16-55 Q1 = A amends the 16-22 rule "SKIPPED
   never holds": under `restart: unless-stopped` an exit 0 would be restarted in a loop).
4. Admission (the user's decision Q-A, `runtime-exact-hash-all`): the runtime process gate
   requires an exact-hash allowlist entry for EVERY parameter set, a fully rationalized one
   included. It runs before any candle is parsed and before `pin_stream_epoch`. A missing entry
   or a hash that differs from the registry file's hash exits 6. A match only lets the existing
   validation continue; `pin_stream_epoch` (unchanged) still judges the set afterwards.
5. The ratified runtime configuration (exit 4 when anything is absent).
6. The single-instance guard (plan 16-55, review B1-WR-07): the instance lease of the state port
   (a PostgreSQL session advisory lock), taken before the pin branch and before any record. A
   lease held by another process refuses the start with exit 8 (a refusal, held under
   `--hold-on-refusal`). The lease is released on every way out and is re-checked by the live
   loop at every consumer batch and every step of its periodic tasks (exit 7 when lost).
7. The epoch: pinned only by the one-shot operator command `--pin-epoch` when no pinned state
   exists; the pin records EPOCH_PINNED, writes the pinned state and exits 0 without
   RUNTIME_START and without the loop (16-DEC-PIN-COMMAND). Every start loads the stored epoch
   and never mints one (exit 5 without a pin, exit 6 on any mismatch). The pin and every
   RUNTIME_START record the identity of the effective configuration (the SHA-256 of its
   canonical, validated values) and, labelled as provenance, the raw file SHA-256 and path;
   every start recomputes the identity and refuses a different one, or a pin without one, with
   exit 6 (plan 16-57, owner decision 16-DEC-CONFIG-PIN). A comment-only edit is not refused.
8. RUNTIME_START, the run, RUNTIME_STOP (recorded only on a clean stop, so a crash leaves a
   START without a STOP, which the coverage code reads as a crash).

Two layers, deliberately different (see config/paper/README.md): the runtime process gate here
(exact-hash authorization for every set) and the per-call rule inside `pin_stream_epoch` (an
entry is required only for a set without rationale tables). Rationale tables never replace
runtime authorization.

Exit codes are the named table `ExitCode` in `src/paper/runtime_config.py`. With the opt-in
flag `--hold-on-refusal` (used by the compose service) a refusal, SKIPPED included, does not
exit: the process logs it, writes no record, starts no loop, leaves the explicit held marker of
`src/paper/held_marker.py` (so `--healthcheck` reports unhealthy, even over a fresh bar of an
earlier run) and returns the code only after SIGTERM or SIGINT, so a restart policy can never
loop on it. Restartable failures are never held. No path of the service command relies on exit 0
to stay down: 0 comes only from the probe, the one-shot pin, the end of a hold or the return after
RUNTIME_STOP following a requested stop (tests/test_paper_runtime_held_state.py).

The live loop (plan 16-26, `run_admitted`) composes the credential-free public adapter, the
`PaperWsAdapter`, the `PaperSupervisor`, ONE bounded asyncio queue, ONE consumer task and the
`BarPipeline`:

    SDK message -> supervisor sink -> `queue.put_nowait` -> consumer -> `BarPipeline.handle` in
    `asyncio.to_thread` -> `RuntimeStatePort`

The receive callbacks only enqueue (research P10): every database write and the whole tick run
off the event loop through the one synchronous state port, wrapped locally with
`asyncio.to_thread` (the Phase 24 item G4-040 choice between threads and an async pool stays
open). A full queue, a failed write or a pipeline error stops the loop, unsubscribes and closes the
adapter and ends the process with `ExitCode.FAIL_CLOSED_RUNTIME` WITHOUT a RUNTIME_STOP record, so
the restart reads the open RUNTIME_START as a crash. A requested stop (SIGTERM or SIGINT)
unsubscribes, closes the adapter and returns normally; `main` then records RUNTIME_STOP.

The feed fails closed (plan 16-56, B1-CR-01). An exhausted WebSocket rebuild runs its REST
backfill and then fails the process closed through the supervisor's `on_fatal` sink. The silence
watchdog (16-DEC-WS-WATCHDOG) wakes at half of `health.feed_silence_timeout_seconds`: when no
kline frame of any stream has arrived for longer than that bound, it enters the supervisor's
bounded drop recovery once (the `WS_DISCONNECT` record marks the feed lost, live bars wait for
the backfill, backfilled bars are history only and never evaluated); when no frame has arrived
when the bound expires again, it fails the process closed. Both routes share one guard, so the
process fails closed through `_fail` exactly once. Exit 7, no RUNTIME_STOP.

Every consumer batch writes one PAPER_TICK_STATS record: the tick time, the batch counts, the
dropped-event counts by reason (a host clock running behind drops closed bars, research P20) and
the measured duration of the `BarPipeline.handle` call (assumption A10: a tick ends well inside a
bar interval). The duration comes from the injected monotonic function and feeds no decision.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
import threading
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import structlog

from src.core.types import Candle
from src.domain.registry import ParameterSet
from src.ops.redaction import configure_logging
from src.paper import held_marker, liveness
from src.paper.bars import BarBuffers
from src.paper.freeze import (
    PaperAllowlistEntry,
    StreamEpoch,
    allowlist_entries,
    find_allowlist_entry,
    load_parameter_set_at_root,
    load_pinned_state,
    pin_stream_epoch,
    resolve_registry_root,
    write_pinned_state,
)
from src.paper.loop import BarContext
from src.paper.market_inputs import (
    ConstraintProvider,
    make_context_factory,
    make_sibling_fetcher,
    measure_clock_skew,
    refresh_forever,
)
from src.paper.pipeline import BarPipeline, HeldBar, PipelineResult
from src.paper.restart import (
    EpochMismatch,
    RestartPlan,
    apply_restart_fence,
    check_epoch_consistency,
    downtime_gaps,
    health_record,
    restart_gap_record,
    restore_runtime,
    supervisor_cursors,
    warm_up,
)
from src.paper.runtime_config import (
    ConfigNotRatified,
    ConfigProvenance,
    ExitCode,
    RuntimeConfig,
    load_runtime_config,
    load_runtime_config_with_provenance,
    read_env,
    refuse_trade_capable_env,
)
from src.paper.runtime_state import (
    INSTANCE_LEASE_SCOPE,
    GapLedger,
    InstanceLease,
    RuntimeRecord,
    RuntimeRecordConflict,
    RuntimeStatePort,
)
from src.paper.shadow_runtime import (
    RiskPassedBar,
    ShadowCoordinator,
    ShadowRuntimeError,
    ShadowWiring,
    build_coordinator,
)
from src.paper.supervisor import PaperSupervisor
from src.paper.vocabulary import (
    GapReason,
    GapRecord,
    HealthState,
    RuntimeEventType,
    SourceTag,
    TaggedBar,
)
from src.persistence.errors import PersistenceError

SKIPPED_EVENT = "SKIPPED (allowlist empty)"
DEFAULT_PINNED_STATE = Path("logs/paper/pinned_epoch.json")

# Capacity of the inbound bar queue. An implementation value (CONTEXT, Claude's discretion), NOT a
# ratified threshold: it only has to hold one REST backfill burst after an outage (a few hundred
# bars per pair) with room to spare. A full queue is never absorbed: the process fails closed.
QUEUE_MAXSIZE = 4096

# The two intervals the loop subscribes to: the 1h setup bars and the 4h context bars.
LOOP_INTERVALS: tuple[str, ...] = ("1h", "4h")

# Origin tag of a PAPER_GAP the supervisor reports (the pipeline writes its own gaps with
# `GAP_DETAIL_*` tags). A close both report is written once: the shared `GapLedger` lets the
# first writer win (plan 16-57, B1-WR-05).
GAP_DETAIL_SUPERVISOR = "SUPERVISOR"

log = structlog.get_logger()


@dataclass(frozen=True)
class RuntimeContext:
    """What the run (plan 16-26) receives once the process has been admitted and started."""

    epoch: StreamEpoch
    config: RuntimeConfig
    state: RuntimeStatePort
    env: Mapping[str, str]
    clock: Callable[[], datetime]
    registry_root: Path | None
    # The time of this run's own RUNTIME_START (set by `main`): markers before it are the previous
    # run, which tells a planned restart from a crash (plan 16-29).
    started_at_utc: datetime | None = None
    # The instance lease `main` holds for this run (plan 16-55); the loop re-checks it.
    lease: InstanceLease | None = None
    # Where the watchdog writes this container's liveness stamp (plan 16-56; `main` passes the
    # pinned-state directory). None writes no stamp.
    liveness_dir: Path | None = None
    # The identity of the effective configuration and the raw-file provenance (plan 16-57,
    # 16-DEC-CONFIG-PIN): recorded in EPOCH_PINNED and RUNTIME_START, compared at every start.
    config_provenance: ConfigProvenance | None = None


def build_parser() -> argparse.ArgumentParser:
    """The command line of the paper process (plan 16-32 parses the compose command with it)."""
    parser = argparse.ArgumentParser(
        prog="python -m src.paper.runtime",
        description="Paper runtime: once-per-process start gate, then the paper loop.",
    )
    parser.add_argument(
        "--hold-on-refusal",
        action="store_true",
        help=(
            "On a refusal (exit codes 3 to 6 and 8) or SKIPPED, log it, write the held marker "
            "and stay up, non-operational, until SIGTERM or SIGINT instead of exiting, so a "
            "restart policy cannot loop on it."
        ),
    )
    parser.add_argument(
        "--pin-epoch",
        action="store_true",
        help=(
            "One-shot operator command: pin the epoch of this trial when no pinned state "
            "exists, then exit 0 without starting the loop. Without it a start needs an "
            "existing pinned state and reuses its epoch. Never combined with --hold-on-refusal."
        ),
    )
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help=(
            "Container probe: print healthy and exit with status zero only while the last "
            "processed closed bar is younger than the ratified maximum age; otherwise print "
            "unhealthy and a reason and exit with status one."
        ),
    )
    parser.add_argument(
        "--liveness",
        action="store_true",
        help=(
            "Paper heartbeat probe: print live and exit with status zero only while this "
            "container holds no held marker and its event-loop stamp and last market message "
            "are both younger than the configured feed silence timeout; otherwise print not "
            "live and a reason and exit with status one. Opens no database or network client."
        ),
    )
    parser.add_argument(
        "--pinned-state",
        type=Path,
        default=DEFAULT_PINNED_STATE,
        help=f"Path of the pinned-state JSON file (default: {DEFAULT_PINNED_STATE.as_posix()}).",
    )
    return parser


def wait_for_stop_signal() -> None:
    """Block until SIGTERM or SIGINT arrives (the production `wait_for_stop`)."""
    stop = threading.Event()

    def _handler(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)
    stop.wait()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _hold(
    code: ExitCode,
    refusal: str,
    *,
    wait_for_stop: Callable[[], None],
    marker_dir: Path,
) -> int:
    """Hold a refused start: write the held marker, wait for the stop, remove the marker.

    The hold is non-operational: nothing here writes a record or builds a client. A hold whose
    marker cannot be written is never entered, because without the marker the probe could read
    an earlier run's fresh bar as healthy (16-DEC-RESTART-POLICY, correction 1): the process exits
    instead, with the refusal code, or with FAIL_CLOSED_RUNTIME for SKIPPED, never with 0.
    """
    try:
        held_marker.write_marker(marker_dir, code=int(code), refusal=refusal)
    except OSError as exc:
        status = int(code) if code is not ExitCode.OK else int(ExitCode.FAIL_CLOSED_RUNTIME)
        print(
            f"paper runtime cannot write its held marker ({type(exc).__name__}); exiting with "
            f"{status} instead of holding, because a hold without the marker could look healthy",
            file=sys.stderr,
        )
        structlog.get_logger().error(
            "paper runtime held marker not written", refusal=refusal, exit_code=status
        )
        return status
    structlog.get_logger().warning("paper runtime held", refusal=refusal, exit_code=int(code))
    try:
        wait_for_stop()
    finally:
        try:
            held_marker.remove_marker(marker_dir)
        except OSError as exc:
            structlog.get_logger().error(
                "paper runtime held marker not removed", error=type(exc).__name__
            )
    return int(code)


def _refuse(
    code: ExitCode,
    reason: str,
    *,
    hold: bool,
    wait_for_stop: Callable[[], None],
    marker_dir: Path,
) -> int:
    """Report a refusal on stderr and in the log; hold until stopped when asked to."""
    print(f"paper runtime refused (exit {int(code)}): {reason}", file=sys.stderr)
    structlog.get_logger().error("paper runtime refused", exit_code=int(code), reason=reason)
    if not hold:
        return int(code)
    return _hold(code, code.name, wait_for_stop=wait_for_stop, marker_dir=marker_dir)


def _skip(*, hold: bool, wait_for_stop: Callable[[], None], marker_dir: Path) -> int:
    """SKIPPED: the allowlist admits nothing. 0 at once, or 0 at the end of a hold."""
    structlog.get_logger().info(SKIPPED_EVENT)
    if not hold:
        return int(ExitCode.OK)
    return _hold(ExitCode.OK, "SKIPPED", wait_for_stop=wait_for_stop, marker_dir=marker_dir)


def _usage_error(message: str) -> int:
    print(f"paper runtime usage error (exit {int(ExitCode.USAGE)}): {message}", file=sys.stderr)
    return int(ExitCode.USAGE)


def _failed_closed(detail: str) -> int:
    print(
        f"paper runtime failed closed (exit {int(ExitCode.FAIL_CLOSED_RUNTIME)}): {detail}",
        file=sys.stderr,
    )
    return int(ExitCode.FAIL_CLOSED_RUNTIME)


def _pinned_and_exit(epoch: StreamEpoch) -> int:
    """The one-shot pin is done (16-DEC-PIN-COMMAND): no RUNTIME_START, no loop, exit 0."""
    structlog.get_logger().info("epoch pinned; the pin command exits", epoch_id=epoch.epoch_id)
    print(f"epoch pinned: {epoch.epoch_id}; start the managed paper service now")
    return int(ExitCode.OK)


def _stopped_on_request() -> int:
    """The loop returned on a requested stop and RUNTIME_STOP is recorded."""
    return int(ExitCode.OK)


def verify_instance_lease(lease: InstanceLease | None) -> None:
    """Fail closed when the instance lease is lost or cannot be verified (plan 16-55, Test 7).

    A session advisory lock disappears silently with its connection (database restart, network
    cut, terminated backend), after which a second runtime could take it. The live loop calls
    this at every consumer batch and every periodic step, so a lost lease is noticed at the next
    one of them.

    Raises:
        RuntimeFailClosed: the lease is not held (exit 7, restartable: the restart takes the
            lease again or is refused).
    """
    if lease is None:
        return
    try:
        held = lease.is_held()
    except Exception:  # noqa: BLE001 - an unverifiable lease is a lost lease
        held = False
    if not held:
        raise RuntimeFailClosed(
            "the instance lease was lost or cannot be verified: another paper runtime could "
            "take this epoch (B1-WR-07)"
        )


def _admit(
    strategy_id: str, parameter_set_id: str, registry_root: Path | None
) -> tuple[PaperAllowlistEntry | None, str | None]:
    """The strict runtime gate (Q-A): an exact-hash entry for this set, rationalized or not.

    Returns (entry, None) when admitted, or (None, reason) when not. Pure admission: it reads
    the allowlist and the registry file and decides nothing else; `pin_stream_epoch` still
    runs its full validation afterwards.
    """
    try:
        entry = find_allowlist_entry(strategy_id, parameter_set_id)
    except ValueError as exc:
        return None, str(exc)
    if entry is None:
        return None, (
            f"no allowlist entry for {strategy_id}/{parameter_set_id}: the runtime gate "
            "requires an exact-hash entry for every parameter set, rationalized or not (Q-A)"
        )
    try:
        file_hash = load_parameter_set_at_root(
            strategy_id, parameter_set_id, resolve_registry_root(registry_root)
        ).parameter_set_hash
    except Exception as exc:  # fail closed on any defect of the file, naming only the type
        return None, f"{strategy_id}/{parameter_set_id}: cannot load the set ({type(exc).__name__})"
    if file_hash != entry.parameter_set_hash:
        return None, (
            f"{strategy_id}/{parameter_set_id}: the allowlist hash {entry.parameter_set_hash} "
            f"does not match the registry file's parameter_set_hash {file_hash}"
        )
    return entry, None


def check_consumer_domains(config: RuntimeConfig) -> None:
    """Refuse, before RUNTIME_START, a value the loader accepted but a consumer would refuse.

    Builds the one SHADOW consumer with its own domain check (`LiveMinutePoller`, no I/O) from
    the configuration (plan 16-56, B1-WR-10 Test 4): a `ValueError` or `TypeError` becomes
    `ConfigNotRatified` (exit 4) instead of a fail-closed exit 7 after the start record.
    """
    from src.paper.live_minutes import LiveMinutePoller, LiveMinuteSource

    try:
        LiveMinutePoller(
            feed=_NoMinuteFeed(),
            source=LiveMinuteSource(),
            poll_interval_seconds=config.timing.minute_poll_interval_seconds,
            close_lag_seconds=config.timing.minute_close_lag_seconds,
        )
    except (ValueError, TypeError) as exc:
        raise ConfigNotRatified(
            [f"timing (a consumer refused a loaded value: {type(exc).__name__}: {exc})"]
        ) from None


class _NoMinuteFeed:
    """The feed of the domain check: never called (the check builds, it does not poll)."""

    async def klines(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the domain check never polls")

    async def mark_klines(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the domain check never polls")


def _state_from_env(values: Mapping[str, str]) -> RuntimeStatePort:
    """The production state port: journal rows on PostgreSQL (Q-J), never an in-memory fallback.

    The engine is `make_sync_engine` (plan 16-56, B1-WR-02): connect, lock, statement and pool
    timeouts, `pool_pre_ping`, TCP keepalives and the UTC session pin, verified by one probe
    connection. An unreachable database raises `StoreUnavailable` and a session that is not on
    UTC raises `SessionTimeZoneNotUtc`; `main` maps both to exit 7 before RUNTIME_START.

    Raises:
        ConfigNotRatified: no database URL, or a URL that does not select PostgreSQL.
    """
    url = values.get("DATABASE_URL_SYNC") or values.get("DATABASE_URL")
    if not url:
        raise ConfigNotRatified(["DATABASE_URL_SYNC or DATABASE_URL"])
    # Imported here so that a SKIPPED start and every refusal never import SQLAlchemy.
    from src.persistence.engine import make_sync_engine
    from src.persistence.paper_runtime_state import PgRuntimeState
    from src.persistence.uow import OperationalDatabase

    try:
        engine = make_sync_engine(url)
    except ValueError:
        raise ConfigNotRatified(
            ["DATABASE_URL_SYNC or DATABASE_URL (must be a postgresql:// URL)"]
        ) from None
    return PgRuntimeState(OperationalDatabase(engine))


def _pg_shadow_stores(url: str) -> Any:
    """The PostgreSQL stores of the SHADOW chain (a seam: tests replace it)."""
    # Imported here so that a SKIPPED start and every refusal never import SQLAlchemy.
    from src.persistence.engine import make_sync_engine
    from src.persistence.shadow_stores import PgShadowStores
    from src.persistence.uow import OperationalDatabase

    return PgShadowStores(OperationalDatabase(make_sync_engine(url)))


def _shadow_from_env(values: Mapping[str, str]) -> ShadowWiring | None:
    """The production SHADOW wiring, or None when the environment does not configure Telegram.

    The bot token and the authorized chat id come from the environment (never logged, never
    printed); the stores are the PostgreSQL ones (Q-J, no in-memory fallback). The Telegram
    application is built at start by `build_application` (Q-L: its own bot, one consumer).
    """
    token = values.get("TELEGRAM_BOT_TOKEN")
    chat = values.get("TELEGRAM_AUTHORIZED_CHAT_ID")
    if not token or not chat:
        return None
    try:
        chat_id = int(chat)
    except ValueError:
        raise ConfigNotRatified(["TELEGRAM_AUTHORIZED_CHAT_ID (must be an integer)"]) from None
    url = values.get("DATABASE_URL_SYNC") or values.get("DATABASE_URL")
    if not url:
        raise ConfigNotRatified(["DATABASE_URL_SYNC or DATABASE_URL"])

    def application_factory(callback_kwargs: dict[str, Any]) -> Any:
        from src.adapters.telegram_callbacks import build_application

        return build_application(token=token, **callback_kwargs)

    return ShadowWiring(
        stores=_pg_shadow_stores(url), chat_id=chat_id, application_factory=application_factory
    )


def _epoch_record(
    event_type: RuntimeEventType,
    epoch: StreamEpoch,
    at: datetime,
    extra: Mapping[str, Any] | None = None,
) -> RuntimeRecord:
    return RuntimeRecord(
        event_type=event_type,
        epoch_id=epoch.epoch_id,
        occurred_at_utc=at,
        payload={
            "strategy_id": epoch.strategy_id,
            "parameter_set_id": epoch.parameter_set_id,
            "parameter_set_hash": epoch.parameter_set_hash,
            **(extra or {}),
        },
    )


class RuntimeFailClosed(Exception):
    """The live loop stopped because continuing could not be trusted (exit code 7, restartable).

    The message is this module's own text (a reason such as "queue is full"); the underlying
    exception of a failed write is reported by its type name only, never by its message.
    """


@runtime_checkable
class SeedsProcessed(Protocol):
    """A pipeline that can mark restored bars as already processed (`BarPipeline`)."""

    def seed_processed(self, last_closes: Mapping[tuple[str, str], datetime]) -> None: ...


class HandlesBars(Protocol):
    """What the consumer needs from the pipeline (`BarPipeline`; a double in tests)."""

    def handle(self, bars: Iterable[TaggedBar], *, now_utc: datetime) -> PipelineResult: ...


@dataclass(frozen=True)
class LoopWiring:
    """Composition and test seams of `run_admitted`; production binds only `risk_inputs`.

    Every field is optional. Left at None the loop builds the production object: the
    credential-free `BinancePublicMarketData`, a real `PaperWsAdapter`, the real `BarPipeline`, the
    signal-driven stop, the monotonic clock and `asyncio.sleep`. `risk_inputs` (the required
    open-positions and daily-loss port) has no default implementation in src: plan 16-31 binds it
    to the SHADOW ledger when `shadow` is given (an explicit `risk_inputs` still wins).

    `shadow` (plan 16-31) is the seam of the SHADOW chain: the stores, the Telegram bot and the
    authorized chat. With it, `run_admitted` builds the `ShadowCoordinator` and hands every
    risk-passed bar outcome to it.
    """

    ws_client: Any | None = None
    ws_client_factory: Callable[[Any], Any] | None = None
    public: Any | None = None
    risk_inputs: Any | None = None
    context_factory: Callable[[Candle], BarContext] | None = None
    pipeline: HandlesBars | None = None
    stop_waiter: Callable[[], Awaitable[None]] | None = None
    monotonic_ms: Callable[[], int] | None = None
    sleep: Callable[[timedelta], Awaitable[None]] | None = None
    queue_maxsize: int | None = None
    shadow: ShadowWiring | None = None
    # The silence watchdog's monotonic seconds and its own sleep (plan 16-56); production binds
    # neither (time.monotonic and asyncio.sleep).
    feed_clock: Callable[[], float] | None = None
    watchdog_sleep: Callable[[timedelta], Awaitable[None]] | None = None
    # The shared written-gap set of the gap writers (plan 16-57, B1-WR-05). Left at None the loop
    # builds one and hands its `claim` to the production pipeline; a test that injects its own
    # pipeline passes the ledger that pipeline claims through.
    gap_ledger: GapLedger | None = None


def _monotonic_ms() -> int:
    """The one monotonic reading of the module (whole milliseconds); it feeds no decision."""
    return time.monotonic_ns() // 1_000_000


async def _real_sleep(delay: timedelta) -> None:
    await asyncio.sleep(delay.total_seconds())


async def _wait_for_stop_signal() -> None:
    """Return when SIGTERM or SIGINT arrives (installed on the main thread, every platform)."""
    loop = asyncio.get_running_loop()
    stopped = asyncio.Event()

    def _handler(_signum: int, _frame: object) -> None:
        loop.call_soon_threadsafe(stopped.set)

    previous = {
        signal.SIGINT: signal.signal(signal.SIGINT, _handler),
        signal.SIGTERM: signal.signal(signal.SIGTERM, _handler),
    }
    try:
        await stopped.wait()
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def _gap_record(epoch_id: str, gap: GapRecord) -> RuntimeRecord:
    """The PAPER_GAP record of a gap the supervisor reported (keyed on the expected close)."""
    return RuntimeRecord(
        event_type=RuntimeEventType.PAPER_GAP,
        epoch_id=epoch_id,
        occurred_at_utc=gap.detected_at_utc,
        symbol=gap.symbol,
        interval=gap.interval,
        payload={
            "expected_close_utc": gap.expected_close_utc,
            "reason": gap.reason.value,
            "source": GAP_DETAIL_SUPERVISOR,
        },
    )


def _risk_passed_bars(state: RuntimeStatePort, epoch_id: str) -> tuple[RiskPassedBar, ...]:
    """The epoch's PAPER_BAR_PROCESSED records of stage `risk_passed` (plan 16-57, B1-WR-03).

    A risk-passed heartbeat without a plan hash or a signal id cannot be checked against the
    SHADOW rows: the start fails closed instead of guessing.
    """
    bars: list[RiskPassedBar] = []
    for record in state.records(epoch_id, {RuntimeEventType.PAPER_BAR_PROCESSED}):
        payload = record.payload
        if payload.get("stage") != "risk_passed":
            continue
        surface = payload.get("surface")
        plan_hash = payload.get("plan_hash")
        signal_id = surface.get("signal_id") if isinstance(surface, Mapping) else None
        if (
            not isinstance(plan_hash, str)
            or not plan_hash
            or not isinstance(signal_id, str)
            or not signal_id
            or record.symbol is None
            or record.interval is None
        ):
            raise RuntimeFailClosed(
                "a risk-passed heartbeat carries no plan hash or signal id: the SHADOW rows "
                "cannot be checked against it"
            )
        bars.append(
            RiskPassedBar(
                symbol=record.symbol,
                interval=record.interval,
                bar_close_utc=record.occurred_at_utc,
                signal_id=signal_id,
                plan_hash=plan_hash,
            )
        )
    return tuple(bars)


def _tick_stats_record(
    *,
    epoch_id: str,
    tick_time: datetime,
    batch_seq: int,
    bars_in: int,
    result: PipelineResult,
    duration_ms: int,
    queue_depth_before: int,
) -> RuntimeRecord:
    """The PAPER_TICK_STATS record of one consumer batch (research P20 and A10).

    `duration_ms` is evidence only; nothing in the loop reads it back to decide anything.
    """
    dropped_by_reason: dict[str, int] = {}
    for dropped in result.dropped:
        key = dropped.reason.value
        dropped_by_reason[key] = dropped_by_reason.get(key, 0) + 1
    return RuntimeRecord(
        event_type=RuntimeEventType.PAPER_TICK_STATS,
        epoch_id=epoch_id,
        occurred_at_utc=tick_time,
        payload={
            "batch_seq": batch_seq,
            "bars_in": bars_in,
            "evaluated": len(result.evaluated),
            "held": len(result.held),
            "duplicates": len(result.duplicates),
            "dropped_total": len(result.dropped),
            "dropped_by_reason": dropped_by_reason,
            "duration_ms": max(0, duration_ms),
            "queue_depth_before": queue_depth_before,
        },
    )


class _LiveLoop:
    """The running composition: sinks, queue, consumer and the shutdown (see the module docstring).

    Everything here runs on the event-loop thread except the two `asyncio.to_thread` calls (the
    pipeline tick and a record write). Failures never raise into the SDK: they are stored once in
    `_failure`, the stop event is set and `run` re-raises after a clean teardown.
    """

    def __init__(
        self,
        *,
        context: RuntimeContext,
        wiring: LoopWiring,
        pipeline: HandlesBars,
        supervisor_factory: Callable[[_LiveLoop], PaperSupervisor],
        restart: RestartPlan,
        constraints: ConstraintProvider | None = None,
        shadow: ShadowCoordinator | None = None,
        gap_ledger: GapLedger | None = None,
    ) -> None:
        self._context = context
        self._restart = restart
        # First writer wins per (symbol, interval, expected close) across the restart, the
        # supervisor and the pipeline (plan 16-57, B1-WR-05).
        self._gaps = gap_ledger if gap_ledger is not None else GapLedger()
        self._shadow = shadow
        self._symbols = context.config.symbols
        # Closes at or before this instant can only be history (see `apply_restart_fence`).
        self._fence: datetime | None = None
        self._live_seen = False
        self._constraints = constraints
        self._epoch_id = context.epoch.epoch_id
        self._state = context.state
        self._lease = context.lease
        self._clock = context.clock
        self._pipeline = pipeline
        self._queue: asyncio.Queue[TaggedBar] = asyncio.Queue(
            maxsize=wiring.queue_maxsize if wiring.queue_maxsize is not None else QUEUE_MAXSIZE
        )
        self._monotonic_ms = (
            wiring.monotonic_ms if wiring.monotonic_ms is not None else _monotonic_ms
        )
        self._sleep = wiring.sleep if wiring.sleep is not None else _real_sleep
        self._stop_waiter = (
            wiring.stop_waiter if wiring.stop_waiter is not None else _wait_for_stop_signal
        )
        self._feed_clock: Callable[[], float] = (
            wiring.feed_clock if wiring.feed_clock is not None else time.monotonic
        )
        self._watchdog_sleep = (
            wiring.watchdog_sleep if wiring.watchdog_sleep is not None else _real_sleep
        )
        self._shutting_down = False
        self._stop = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()
        self._failure: BaseException | None = None
        self._batch_seq = 0
        self._tasks: set[asyncio.Task[None]] = set()
        self._record_tasks: set[asyncio.Task[None]] = set()
        self._supervisor = supervisor_factory(self)

    # ---- the SDK-facing callbacks: enqueue or schedule, never touch the store ------------- #

    def sinks(self) -> dict[str, Any]:
        return {
            "on_closed_bar": self._sink_closed_bar,
            "on_backfill": self._sink_backfill,
            "on_gap": self._sink_gap,
            "on_connection_event": self._sink_connection_event,
            "on_fatal": self._sink_fatal,
        }

    @property
    def feed_clock(self) -> Callable[[], float]:
        """The watchdog's monotonic seconds, shared with the supervisor's frame stamp."""
        return self._feed_clock

    def _sink_closed_bar(self, bar: TaggedBar) -> None:
        self._enqueue(bar)

    def _sink_backfill(self, bar: TaggedBar) -> None:
        self._enqueue(bar)

    def _sink_gap(self, gap: GapRecord) -> None:
        if not self._gaps.claim(gap.symbol, gap.interval, gap.expected_close_utc):
            # B1-WR-05: the pipeline or the restart recorded this close first; its record stands.
            log.info(
                "paper runtime: a gap already recorded by another writer is not written again",
                symbol=gap.symbol,
                interval=gap.interval,
            )
            return
        self._spawn_record(_gap_record(self._epoch_id, gap))

    def _sink_connection_event(self, event: RuntimeEventType, at: datetime) -> None:
        self._spawn_record(
            RuntimeRecord(event_type=event, epoch_id=self._epoch_id, occurred_at_utc=at)
        )

    def _sink_fatal(self, reason: str) -> None:
        """The supervisor's rebuild was exhausted after its backfill (B1-CR-01): exit 7."""
        self._fail_feed(reason)

    def _enqueue(self, bar: TaggedBar) -> None:
        if self._fence is not None:
            bar = apply_restart_fence(bar, self._fence)
        if bar.source is SourceTag.LIVE_WS and not self._live_seen:
            # The first live closed event after the warm-up ends the declared DISCONNECTED state.
            self._live_seen = True
            # Strictly after the DISCONNECTED record of this start: a health record is keyed on
            # its time, so two states in the same millisecond would be one conflicting record.
            at = max(self._clock(), self._restart.started_at_utc + timedelta(milliseconds=1))
            self._spawn_record(health_record(self._epoch_id, HealthState.HEALTHY, at))
        try:
            self._queue.put_nowait(bar)
        except asyncio.QueueFull:
            self._fail(RuntimeFailClosed("the inbound bar queue is full: a bar cannot be dropped"))
            raise

    def _spawn_record(self, record: RuntimeRecord) -> None:
        task = asyncio.get_running_loop().create_task(self._write_record(record))
        self._record_tasks.add(task)
        task.add_done_callback(self._record_tasks.discard)

    async def _write_record(self, record: RuntimeRecord) -> None:
        try:
            await asyncio.to_thread(self._state.record, record)
        except Exception as exc:
            self._fail(exc)

    # ---- failure --------------------------------------------------------------------------- #

    def _fail(self, exc: BaseException) -> None:
        if self._failure is None:
            self._failure = exc
            reason = str(exc) if isinstance(exc, RuntimeFailClosed) else type(exc).__name__
            log.error("paper runtime failing closed", reason=reason)
        self._stop.set()

    def _fail_feed(self, reason: str) -> None:
        """The one guard of the two feed routes to exit 7 (the exhaustion sink and the watchdog).

        Neither route calls `_fail` once a failure is stored, the stop is set or the teardown has
        begun, so the process fails closed through `_fail` exactly once (plan 16-56, Test 1b).
        """
        if self._failure is not None or self._stop.is_set() or self._shutting_down:
            log.info("paper runtime: a later feed failure cause is ignored", reason=reason)
            return
        self._fail(RuntimeFailClosed(reason))

    # ---- the silence watchdog (plan 16-56, 16-DEC-WS-WATCHDOG) ------------------------------ #

    def _finished(self) -> bool:
        return self._stop.is_set() or self._shutting_down or self._failure is not None

    async def _watch_feed(self) -> None:
        """Detect a silent market connection; recover once within the bounds, else fail closed.

        Wakes at half the bound (a STRUCTURAL sampling rate: a live loop then always has a stamp
        younger than the bound). The bound is only the configuration's
        `health.feed_silence_timeout_seconds`. The silence is measured from the supervisor's
        connection-wide last-frame stamp, or from the watchdog's start before the first frame. A
        silence longer than the bound starts the supervisor's bounded drop recovery once per
        episode; a frame arriving after the silence began ends the episode; when the bound
        expires again with no frame since the silence began, the process fails closed.
        """
        bound = self._context.config.health.feed_silence_timeout_seconds
        wake = timedelta(seconds=bound) / 2
        watch_started = self._feed_clock()
        self._stamp_liveness(watch_started, watch_started)
        silent_since: float | None = None
        recovery_started: float | None = None
        while not self._finished():
            await self._watchdog_sleep(wake)
            if self._finished():
                return
            now = self._feed_clock()
            last = self._supervisor.last_frame_monotonic
            reference = watch_started if last is None else max(last, watch_started)
            self._stamp_liveness(now, reference)
            if recovery_started is None or silent_since is None:
                if now - reference > bound:
                    silent_since, recovery_started = reference, now
                    log.error(
                        "paper runtime: market stream silent, entering the bounded recovery",
                        silent_seconds=int(now - reference),
                    )
                    self._start_silence_recovery()
            elif last is not None and last > silent_since:
                log.info("paper runtime: market stream resumed after the recovery")
                silent_since = recovery_started = None
            elif now - recovery_started >= bound:
                self._fail_feed(
                    "market stream silent: no message on the connection since the silence began, "
                    "after the bounded recovery (B1-CR-01, 16-DEC-WS-WATCHDOG)"
                )
                return

    def _stamp_liveness(self, now: float, last_frame: float) -> None:
        """Write this container's liveness stamp from the event loop (plan 16-56 Task 4).

        The wall-clock time of the last message is derived from the feed clock, so the SDK
        handler's stamp stays one attribute write. A failed write is logged and never fails the
        loop: the probe then reports not live and the heartbeat stops.
        """
        directory = self._context.liveness_dir
        if directory is None:
            return
        at = self._clock()
        try:
            liveness.write_liveness(
                directory,
                loop_alive_utc=at,
                last_frame_utc=at - timedelta(seconds=max(0, now - last_frame)),
            )
        except (OSError, ValueError) as exc:
            log.warning(
                "paper runtime: the liveness stamp was not written", error=type(exc).__name__
            )

    def _start_silence_recovery(self) -> None:
        task = asyncio.get_running_loop().create_task(self._recover_from_silence())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _recover_from_silence(self) -> None:
        await self._supervisor.recover_from_silence()

    # ---- the instance lease (plan 16-55, B1-WR-07) ----------------------------------------- #

    async def _check_lease(self) -> None:
        """Verify the lease off the event loop; a lost lease fails the loop closed."""
        if self._lease is None:
            return
        try:
            await asyncio.to_thread(verify_instance_lease, self._lease)
        except RuntimeFailClosed as exc:
            self._fail(exc)
            raise

    async def _sleep_then_check_lease(self, delay: timedelta) -> None:
        """The refresh loop's sleep, followed by the lease check of that periodic step."""
        await self._sleep(delay)
        await self._check_lease()

    # ---- the consumer ---------------------------------------------------------------------- #

    async def _consume(self) -> None:
        try:
            while True:
                first = await self._queue.get()
                self._idle.clear()
                try:
                    await self._process_batch(first)
                finally:
                    self._idle.set()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail(exc)

    async def _process_batch(self, first: TaggedBar) -> None:
        await self._check_lease()  # before the batch writes anything
        depth_before = self._queue.qsize() + 1  # the batch itself plus what waits behind it
        bars = [first]
        while True:
            try:
                bars.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        now = self._clock()
        started = self._monotonic_ms()
        result = await asyncio.to_thread(self._pipeline.handle, bars, now_utc=now)
        finished = self._monotonic_ms()
        stats = _tick_stats_record(
            epoch_id=self._epoch_id,
            tick_time=now,
            batch_seq=self._batch_seq,
            bars_in=len(bars),
            result=result,
            duration_ms=finished - started,
            queue_depth_before=depth_before,
        )
        self._batch_seq += 1
        await asyncio.to_thread(self._state.record, stats)
        for held in result.held:
            self._schedule_resubmit(held)
        if self._shadow is not None:
            # A risk-passed outcome becomes a SHADOW alert (plan 16-31); every other outcome is
            # ignored. A failed store write raises here and fails the loop closed.
            await self._shadow.on_result(result)

    def _schedule_resubmit(self, held: HeldBar) -> None:
        task = asyncio.get_running_loop().create_task(self._resubmit(held))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _resubmit(self, held: HeldBar) -> None:
        """Hand a held 1h bar back to the consumer once its sibling deadline has passed."""
        try:
            wait = held.deadline_utc - self._clock()
            if wait > timedelta(0):
                await self._sleep(wait)
            self._enqueue(held.bar)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail(exc)

    # ---- run and teardown ------------------------------------------------------------------ #

    async def _restore_before_subscribing(self) -> None:
        """Record the downtime, rebuild the engine windows and seed the supervisor (plan 16-29).

        Everything here happens before the first subscription, so the first live bar meets full
        windows, a seeded cursor and a fence; a warm-up bar is history, never a record.
        """
        plan = self._restart
        records = [
            health_record(
                self._epoch_id,
                HealthState.DISCONNECTED,
                plan.started_at_utc,
                GapReason.WS_RECONNECT_WINDOW,
            ),
            *(restart_gap_record(self._epoch_id, gap) for gap in plan.gaps),
        ]
        for record in records:
            await asyncio.to_thread(self._state.record, record)
        # Every gap the store held at the restore and every restart gap just written is taken:
        # a later writer of the same close skips its record (B1-WR-05).
        self._gaps.seed(plan.restored.recorded_gaps)
        self._gaps.seed({(g.symbol, g.interval, g.expected_close_utc) for g in plan.gaps})
        if plan.warm.bars:
            result = await asyncio.to_thread(
                self._pipeline.handle, plan.warm.bars, now_utc=plan.snapshot_utc
            )
            if result.evaluated or result.recorded:
                raise RuntimeFailClosed("the REST warm-up evaluated or recorded a bar")
        if isinstance(self._pipeline, SeedsProcessed):
            self._pipeline.seed_processed(plan.restored.last_closes)
        cursors = supervisor_cursors(
            plan.restored, plan.warm, symbols=self._symbols, intervals=LOOP_INTERVALS
        )
        for (symbol, interval), close in cursors.items():
            self._supervisor.record_close(symbol, interval, close)
        self._fence = plan.snapshot_utc

    async def _run_shadow_poller(self) -> None:
        """The SHADOW minute poller as a loop task: any error fails the loop closed."""
        if self._shadow is None:
            return
        try:
            await self._shadow.run_poller(self._stop, before_step=self._check_lease)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail(exc)

    async def run(self) -> None:
        await self._restore_before_subscribing()
        if self._shadow is not None:
            # The SHADOW chain starts before the first subscription (plan 16-31): its Telegram
            # application polls getUpdates in this event loop. Its restore journals every
            # risk-passed bar of the epoch whose alert never persisted (B1-WR-03); the records
            # are read here, so the chain never reads the runtime state itself.
            risk_passed = await asyncio.to_thread(_risk_passed_bars, self._state, self._epoch_id)
            try:
                await self._shadow.start(risk_passed=risk_passed)
            except Exception as exc:
                raise RuntimeFailClosed(
                    f"the SHADOW chain failed to start ({type(exc).__name__})"
                ) from exc
        try:
            await self._supervisor.start()
        except Exception as exc:
            if self._shadow is not None:
                await self._shadow.stop()
            raise RuntimeFailClosed(f"the WebSocket start failed ({type(exc).__name__})") from exc
        # B1-WR-01: the SDK's `open` echo fires inside `start()` and is ignored, so one
        # verification backfill closes the seam between the warm-up snapshot and the first
        # subscription. Its bars and gaps are queued before the consumer starts; live bars that
        # arrive meanwhile are held by the supervisor and delivered after them.
        try:
            await self._supervisor.verify_start_seam()
        except Exception as exc:
            await self._supervisor.stop()
            if self._shadow is not None:
                await self._shadow.stop()
            raise RuntimeFailClosed(
                f"the start-up seam verification failed ({type(exc).__name__})"
            ) from exc
        consumer = asyncio.create_task(self._consume())
        self._tasks.add(asyncio.create_task(self._watch_feed()))
        if self._shadow is not None:
            self._tasks.add(asyncio.create_task(self._run_shadow_poller()))
        if self._constraints is not None:
            every = timedelta(seconds=self._context.config.timing.exchange_info_refresh_seconds)
            self._tasks.add(
                asyncio.create_task(
                    refresh_forever(
                        self._constraints, every=every, sleep=self._sleep_then_check_lease
                    )
                )
            )
        stopper: asyncio.Future[None] = asyncio.ensure_future(self._stop_waiter())
        failed: asyncio.Future[Any] = asyncio.ensure_future(self._stop.wait())
        try:
            await asyncio.wait({stopper, failed}, return_when=asyncio.FIRST_COMPLETED)
            if stopper.done() and not stopper.cancelled() and stopper.exception() is not None:
                self._fail(stopper.exception() or RuntimeFailClosed("the stop waiter failed"))
        finally:
            await self._shutdown(consumer, stopper, failed)
        failure = self._failure
        if failure is None:
            return
        if isinstance(failure, (RuntimeFailClosed, PersistenceError, RuntimeRecordConflict)):
            raise failure
        raise RuntimeFailClosed(f"the loop failed ({type(failure).__name__})") from failure

    async def _shutdown(self, consumer: asyncio.Task[None], *waiters: asyncio.Future[Any]) -> None:
        """Unsubscribe and close first, let a running batch finish, then cancel the rest."""
        self._shutting_down = True  # no feed route may fail the process from here on
        await self._supervisor.stop()
        if self._shadow is not None:
            # Reverse of the start order: the feed first, then the Telegram application.
            try:
                await self._shadow.stop()
            except Exception as exc:
                log.warning(
                    "paper runtime: the SHADOW chain did not stop cleanly", error=type(exc).__name__
                )
        await self._idle.wait()
        pending: list[asyncio.Future[Any]] = [consumer, *waiters, *self._tasks]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await asyncio.gather(*self._record_tasks, return_exceptions=True)


def _resolve_public(wiring: LoopWiring) -> Any:
    """The public adapter of the wiring, or the credential-free production one."""
    if wiring.public is not None:
        return wiring.public
    from src.adapters.binance_public import BinancePublicMarketData

    # SDK transport errors leave the adapter as project errors (B1-WR-06): the minute poller's
    # one retry names `TransientMarketDataError`, and src/paper never imports an SDK type.
    return BinancePublicMarketData(project_transport_errors=True)


async def run_admitted(context: RuntimeContext, wiring: LoopWiring | None = None) -> None:
    """Run the live paper loop for an admitted, started process until it is told to stop.

    Returns after a requested stop (the caller then records RUNTIME_STOP). Raises
    `RuntimeFailClosed` (or the persistence errors `main` maps to the same exit code) after the
    adapter has been unsubscribed and closed, when the loop stopped itself.
    """
    from src.adapters.paper_ws import PaperWsAdapter

    live = wiring if wiring is not None else LoopWiring()
    config = context.config
    epoch = context.epoch
    loop = asyncio.get_running_loop()
    public = _resolve_public(live)

    pipeline = live.pipeline
    factory = live.context_factory
    gap_ledger = live.gap_ledger if live.gap_ledger is not None else GapLedger()
    constraints: ConstraintProvider | None = None
    shadow: ShadowCoordinator | None = None
    parameter_set: ParameterSet | None = None
    if pipeline is None or live.shadow is not None:
        parameter_set = load_parameter_set_at_root(
            epoch.strategy_id, epoch.parameter_set_id, resolve_registry_root(context.registry_root)
        )
        if (
            pipeline is None
            and factory is None
            and live.risk_inputs is None
            and live.shadow is None
        ):
            raise RuntimeFailClosed("the risk inputs port is not bound")
        if live.shadow is not None or (pipeline is None and factory is None):
            constraints = ConstraintProvider(
                public=public, symbols=config.symbols, clock=context.clock
            )
            try:
                await constraints.refresh()
            except Exception as exc:
                raise RuntimeFailClosed(
                    f"the first exchangeInfo refresh failed ({type(exc).__name__})"
                ) from exc
        if live.shadow is not None:
            if constraints is None:
                raise RuntimeFailClosed("the SHADOW chain needs the exchange constraints")
            try:
                shadow = build_coordinator(
                    live.shadow,
                    epoch=epoch,
                    config=config,
                    clock=context.clock,
                    parameter_set=parameter_set,
                    constraints=constraints,
                    public=public,
                )
            except ShadowRuntimeError as exc:
                raise RuntimeFailClosed(str(exc)) from exc
    if pipeline is None:
        if parameter_set is None:
            raise RuntimeFailClosed("the parameter set was not loaded")
        if factory is None:
            risk_inputs = live.risk_inputs
            if risk_inputs is None and shadow is not None:
                risk_inputs = shadow.risk_inputs
            if risk_inputs is None or constraints is None:
                raise RuntimeFailClosed("the risk inputs port is not bound")
            factory = make_context_factory(
                parameter_set=parameter_set,
                constraints=constraints,
                risk_inputs=risk_inputs,
                account=config.account,
                ttl_seconds=config.timing.constraint_snapshot_ttl_seconds,
            )
        pipeline = BarPipeline(
            epoch=epoch,
            parameter_set=parameter_set,
            context_factory=factory,
            buffers=BarBuffers(),
            state=context.state,
            sibling_4h_wait_seconds=config.timing.sibling_4h_wait_seconds,
            fetch_4h_bar=make_sibling_fetcher(public, loop),
            claim_gap=gap_ledger.claim,
        )

    def build_supervisor(owner: _LiveLoop) -> PaperSupervisor:
        adapter = PaperWsAdapter(ws_client=live.ws_client, client_factory=live.ws_client_factory)
        sinks = owner.sinks()
        return PaperSupervisor(
            ws_adapter=adapter,
            rest_adapter=public,
            symbols=config.symbols,
            intervals=LOOP_INTERVALS,
            on_closed_bar=sinks["on_closed_bar"],
            on_backfill=sinks["on_backfill"],
            on_gap=sinks["on_gap"],
            on_connection_event=sinks["on_connection_event"],
            clock=context.clock,
            on_fatal=sinks["on_fatal"],
            feed_clock=owner.feed_clock,
        )

    snapshot = context.clock()
    started = context.started_at_utc if context.started_at_utc is not None else snapshot
    try:
        restored = await asyncio.to_thread(
            restore_runtime, context.state, epoch.epoch_id, current_start_utc=started
        )
        warm = await warm_up(public, config.symbols, LOOP_INTERVALS, snapshot)
    except (PersistenceError, RuntimeRecordConflict):
        raise
    except Exception as exc:
        raise RuntimeFailClosed(
            f"the restart restore or the REST warm-up failed ({type(exc).__name__})"
        ) from exc
    plan = RestartPlan(
        started_at_utc=started,
        snapshot_utc=snapshot,
        restored=restored,
        warm=warm,
        gaps=downtime_gaps(
            restored,
            now_utc=snapshot,
            symbols=config.symbols,
            intervals=LOOP_INTERVALS,
            warm=warm,
        ),
    )

    await _LiveLoop(
        context=context,
        wiring=live,
        pipeline=pipeline,
        supervisor_factory=build_supervisor,
        restart=plan,
        constraints=constraints,
        shadow=shadow,
        gap_ledger=gap_ledger,
    ).run()


def _healthcheck(
    *,
    env: Mapping[str, str],
    pinned_path: Path,
    state: RuntimeStatePort | None,
    registry_root: Path | None,
    now: Callable[[], datetime],
) -> int:
    """The container probe: 0 only for a running process that keeps processing closed bars.

    Liveness is not health (research P5): a process that is up but processes nothing, a held
    refusal (`--hold-on-refusal` keeps the container up after a refusal) and a stopped process all
    report unhealthy. The held marker of this container is checked first (plan 16-55), then the
    start gate's own refusal checks, so the probe exits 1 wherever the start was or would be
    refused. Only the NAMES of offending variables are ever printed.
    """

    def unhealthy(reason: str) -> int:
        print(f"unhealthy: {reason}")
        return 1

    # A held refused start first, before any bar age: the store may hold a fresh bar of an
    # earlier run (16-DEC-RESTART-POLICY, correction 1). Only this container's marker counts,
    # and the probe never removes it.
    try:
        held = held_marker.read_own_marker(pinned_path.parent)
    except OSError as exc:
        return unhealthy(f"the held marker cannot be read ({type(exc).__name__})")
    if held is not None:
        return unhealthy(
            f"the start was refused and this container is held ({held.refusal}, exit "
            f"{held.code}): it runs no loop; read the container log"
        )

    trade_names = refuse_trade_capable_env(env)
    if trade_names:
        return unhealthy("trade-capable variable present: " + ", ".join(trade_names))
    if not allowlist_entries():
        return unhealthy("the allowlist admits nothing: no paper process runs")
    values = read_env(env)
    absent = [
        name for name in ("PAPER_STRATEGY_ID", "PAPER_PARAMETER_SET_ID") if not values.get(name)
    ]
    if absent:
        return unhealthy("runtime configuration not ratified: " + ", ".join(absent))
    entry, why_not = _admit(
        values["PAPER_STRATEGY_ID"], values["PAPER_PARAMETER_SET_ID"], registry_root
    )
    if entry is None:
        return unhealthy(why_not or "not admitted")
    try:
        config = load_runtime_config(values.get("PAPER_RUNTIME_CONFIG"))
    except ConfigNotRatified as exc:
        return unhealthy(str(exc))
    if not pinned_path.is_file():
        return unhealthy("no pinned epoch")
    try:
        epoch = load_pinned_state(pinned_path)
    except (OSError, ValueError, KeyError, TypeError):
        return unhealthy("the pinned state is unreadable")
    if epoch.parameter_set_hash != entry.parameter_set_hash:
        return unhealthy("the pinned state does not match the admitted allowlist entry")
    try:
        port = state if state is not None else _state_from_env(values)
        marker = port.latest_runtime_marker(epoch.epoch_id)
        closes = port.last_close_by_pair(epoch.epoch_id)
    except ConfigNotRatified as exc:
        return unhealthy(str(exc))
    except Exception as exc:  # the probe must answer, never crash, on a store problem
        return unhealthy(f"the runtime state is unreadable ({type(exc).__name__})")

    if marker is None or marker.event_type is not RuntimeEventType.RUNTIME_START:
        return unhealthy("no running process is recorded")
    max_age = timedelta(seconds=config.timing.healthcheck_max_bar_age_seconds)
    at = now()
    started = marker.occurred_at_utc
    last_bar = max(closes.values(), default=None)
    if last_bar is not None and last_bar >= started:
        if at - last_bar <= max_age:
            print("healthy")
            return 0
        return unhealthy("the last processed closed bar is older than the maximum age")
    if at - started <= max_age:
        print("healthy: waiting for the first closed bar since the start")
        return 0
    return unhealthy("no closed bar was processed within the maximum age after the start")


def _liveness(*, env: Mapping[str, str], pinned_path: Path, now: Callable[[], datetime]) -> int:
    """The paper heartbeat probe (plan 16-56, 16-DEC-HUNG-RUNTIME, correction 2).

    0 only when this container holds no held marker and its liveness stamp shows an event-loop
    wake and a market message both within `health.feed_silence_timeout_seconds`. It reads the
    configuration named by `PAPER_RUNTIME_CONFIG` and two small files; it opens no database,
    network or Telegram client and prints names and ages only, never a value.
    """

    def not_live(reason: str) -> int:
        print(f"not live: {reason}")
        return 1

    values = read_env(env)
    try:
        config = load_runtime_config(values.get("PAPER_RUNTIME_CONFIG"))
    except ConfigNotRatified as exc:
        return not_live(str(exc))
    problem = liveness.liveness_problem(
        pinned_path.parent,
        now_utc=now(),
        bound_seconds=config.health.feed_silence_timeout_seconds,
    )
    if problem is not None:
        return not_live(problem)
    print("live")
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    wait_for_stop: Callable[[], None] | None = None,
    state: RuntimeStatePort | None = None,
    registry_root: Path | None = None,
    clock: Callable[[], datetime] | None = None,
    run_loop: Callable[[RuntimeContext], None] | None = None,
    wiring: LoopWiring | None = None,
) -> int:
    """Run the paper process: start gate, admission, lease, epoch, run; returns the exit status.

    The keyword parameters are test and composition seams; production passes none of them. Every
    `return` below is one kind of the exit-0 inventory in tests/test_paper_runtime_held_state.py.
    """
    args = build_parser().parse_args(argv)
    env: Mapping[str, str] = os.environ if environ is None else environ
    configure_logging(env)
    stopper = wait_for_stop if wait_for_stop is not None else wait_for_stop_signal
    now = clock if clock is not None else _utc_now
    hold: bool = args.hold_on_refusal
    pinned_path: Path = args.pinned_state
    marker_dir = pinned_path.parent

    if args.liveness:
        return _liveness(env=env, pinned_path=pinned_path, now=now)
    if args.healthcheck:
        return _healthcheck(
            env=env,
            pinned_path=pinned_path,
            state=state,
            registry_root=registry_root,
            now=now,
        )
    if args.pin_epoch and hold:
        return _usage_error(
            "--pin-epoch is a one-shot operator command that never holds "
            "(16-DEC-PIN-COMMAND); run it without --hold-on-refusal"
        )

    lease: InstanceLease | None = None

    def refuse(code: ExitCode, reason: str) -> int:
        # A held process owns nothing: the lease goes before the hold, so the one-shot pin or a
        # corrected start can take it while this container waits for its stop.
        nonlocal lease
        if lease is not None:
            lease.release()
            lease = None
        return _refuse(code, reason, hold=hold, wait_for_stop=stopper, marker_dir=marker_dir)

    trade_names = refuse_trade_capable_env(env)
    if trade_names:
        return refuse(
            ExitCode.TRADE_KEY_REFUSED,
            "trade-capable variable present: " + ", ".join(trade_names),
        )

    if not allowlist_entries():
        return _skip(hold=hold, wait_for_stop=stopper, marker_dir=marker_dir)

    values = read_env(env)
    absent = [
        name for name in ("PAPER_STRATEGY_ID", "PAPER_PARAMETER_SET_ID") if not values.get(name)
    ]
    if absent:
        return refuse(
            ExitCode.CONFIG_NOT_RATIFIED,
            "runtime configuration not ratified: " + ", ".join(absent),
        )
    strategy_id = values["PAPER_STRATEGY_ID"]
    parameter_set_id = values["PAPER_PARAMETER_SET_ID"]

    entry, why_not = _admit(strategy_id, parameter_set_id, registry_root)
    if entry is None:
        return refuse(ExitCode.ADMISSION_OR_EPOCH_MISMATCH, why_not or "not admitted")

    try:
        config, provenance = load_runtime_config_with_provenance(values.get("PAPER_RUNTIME_CONFIG"))
        check_consumer_domains(config)
        port = state if state is not None else _state_from_env(values)
    except ConfigNotRatified as exc:
        return refuse(ExitCode.CONFIG_NOT_RATIFIED, str(exc))
    except PersistenceError as exc:
        # StoreUnavailable, SessionTimeZoneNotUtc or another construction failure (B1-WR-02):
        # restartable, one line naming the type only, never a traceback.
        return _failed_closed(f"the runtime state database is unusable ({type(exc).__name__})")

    # The single-instance guard (B1-WR-07): before the pin branch and before any record.
    try:
        lease = port.acquire_instance_lease(INSTANCE_LEASE_SCOPE)
    except PersistenceError as exc:
        return _failed_closed(f"the instance lease could not be taken ({type(exc).__name__})")
    if lease is None:
        return refuse(
            ExitCode.INSTANCE_LEASE_HELD,
            "another paper runtime or pin holds the instance lease of this database: one "
            "runtime per epoch (B1-WR-07); stop the other process first",
        )
    try:
        if args.pin_epoch:
            if pinned_path.exists():
                return refuse(
                    ExitCode.ADMISSION_OR_EPOCH_MISMATCH,
                    "a pinned state exists: a new pin restarts the qualifying trial (REV-18), "
                    "so the operator archives the old state first",
                )
            try:
                epoch = pin_stream_epoch(
                    strategy_id=strategy_id,
                    parameter_set_id=parameter_set_id,
                    opened_at_utc=now(),
                    registry_root=registry_root,
                )
            except Exception as exc:  # the per-call validation refuses in many typed ways
                return refuse(
                    ExitCode.ADMISSION_OR_EPOCH_MISMATCH,
                    f"pin_stream_epoch refused ({type(exc).__name__}): {exc}",
                )
            if epoch.parameter_set_hash != entry.parameter_set_hash:
                return refuse(
                    ExitCode.ADMISSION_OR_EPOCH_MISMATCH,
                    "the pinned set's hash changed between admission and the pin",
                )
            try:
                # Recorded before the file is written: a failed write leaves an orphan record of
                # an epoch no run uses, while the reverse order would leave a trial with no pin
                # record.
                port.record(
                    _epoch_record(
                        RuntimeEventType.EPOCH_PINNED,
                        epoch,
                        epoch.opened_at_utc,
                        provenance.record_fields(),
                    )
                )
                write_pinned_state(epoch, pinned_path)
            except (PersistenceError, RuntimeRecordConflict) as exc:
                return _failed_closed(type(exc).__name__)
            return _pinned_and_exit(epoch)

        live_wiring: LoopWiring | None = None
        if run_loop is None:
            live_wiring = wiring if wiring is not None else LoopWiring()
            if (
                live_wiring.pipeline is None
                and live_wiring.context_factory is None
                and live_wiring.risk_inputs is None
                and live_wiring.shadow is None
            ):
                # The production binding of the risk inputs is the SHADOW ledger (plan 16-31),
                # which needs the Telegram chat and the database of the environment.
                try:
                    configured = _shadow_from_env(values)
                except ConfigNotRatified as exc:
                    return refuse(ExitCode.CONFIG_NOT_RATIFIED, str(exc))
                except PersistenceError as exc:
                    return _failed_closed(
                        f"the SHADOW store database is unusable ({type(exc).__name__})"
                    )
                if configured is None:
                    return refuse(
                        ExitCode.CONFIG_NOT_RATIFIED,
                        "the risk inputs port is not bound: open positions and the daily loss "
                        "have no default implementation in src (they come from the SHADOW "
                        "ledger, which needs TELEGRAM_BOT_TOKEN and TELEGRAM_AUTHORIZED_CHAT_ID)",
                    )
                live_wiring = replace(live_wiring, shadow=configured)

        if not pinned_path.is_file():
            return refuse(
                ExitCode.NO_PINNED_EPOCH,
                "no pinned epoch: pinning is an operator command (O-11 iii)",
            )
        try:
            epoch = load_pinned_state(pinned_path)
        except (OSError, ValueError, KeyError, TypeError):
            return refuse(ExitCode.ADMISSION_OR_EPOCH_MISMATCH, "the pinned state is unreadable")
        if (
            epoch.strategy_id != strategy_id
            or epoch.parameter_set_id != parameter_set_id
            or epoch.parameter_set_hash != entry.parameter_set_hash
        ):
            return refuse(
                ExitCode.ADMISSION_OR_EPOCH_MISMATCH,
                "the pinned state does not match the admitted allowlist entry",
            )

        context = RuntimeContext(
            epoch=epoch,
            config=config,
            state=port,
            env=values,
            clock=now,
            registry_root=registry_root,
            lease=lease,
            liveness_dir=marker_dir,
            config_provenance=provenance,
        )
        try:
            # A start never mints an epoch: the pin file and the stored pin record must agree,
            # and so must the effective configuration (16-DEC-CONFIG-PIN, B1-WR-08).
            check_epoch_consistency(epoch, port, config_identity=provenance.identity)
            # A marker left by a killed hold of this container goes before the start is
            # recorded (the probe never removes one).
            try:
                held_marker.remove_marker(marker_dir)
            except OSError as exc:
                raise RuntimeFailClosed(
                    f"the held marker of this container cannot be removed ({type(exc).__name__})"
                ) from exc
            start_extra: dict[str, Any] = dict(provenance.record_fields())
            if run_loop is None and live_wiring is not None:
                public = _resolve_public(live_wiring)
                live_wiring = replace(live_wiring, public=public)
                try:
                    skew_ms = asyncio.run(measure_clock_skew(public, now))
                except Exception as exc:
                    raise RuntimeFailClosed(
                        f"the clock-skew check against Binance server time failed "
                        f"({type(exc).__name__})"
                    ) from exc
                start_extra["clock_skew_ms"] = skew_ms
                structlog.get_logger().info("clock skew measured", clock_skew_ms=skew_ms)
            started_at = now()
            context = replace(context, started_at_utc=started_at)
            port.record(
                _epoch_record(RuntimeEventType.RUNTIME_START, epoch, started_at, start_extra)
            )
            structlog.get_logger().info("runtime start", epoch_id=epoch.epoch_id)
            if run_loop is not None:
                run_loop(context)
            else:
                asyncio.run(run_admitted(context, live_wiring))
            port.record(_epoch_record(RuntimeEventType.RUNTIME_STOP, epoch, now()))
        except EpochMismatch as exc:
            return refuse(ExitCode.ADMISSION_OR_EPOCH_MISMATCH, str(exc))
        except (PersistenceError, RuntimeRecordConflict, RuntimeFailClosed) as exc:
            detail = str(exc) if isinstance(exc, RuntimeFailClosed) else type(exc).__name__
            return _failed_closed(detail)
        return _stopped_on_request()
    finally:
        if lease is not None:
            lease.release()


if __name__ == "__main__":
    raise SystemExit(main())
