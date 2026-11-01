"""The command line of the live process: `python -m src.live.runtime` (plan 24-11; D-02, D-03).

The shape is that of the paper runtime (the proven pattern: hold instead of crash-loop, a held
marker the probe reads, probes that open no client) with the credential rule inverted: the live
process needs ONE mode's Binance names and refuses the other's. It never imports the paper
runtime module (D-01); it uses only the held marker helper of `src/paper/held_marker.py`.

Verbs:

- `--hold-on-refusal`: a refused start writes the held marker and stays up, non-operational,
  until SIGTERM or SIGINT instead of exiting, so a restart policy cannot crash-loop on it
  (T-24-30). The marker makes `--liveness` and `--healthcheck` report unhealthy.
- `--liveness`: exit 0 only with no held marker and a liveness stamp younger than
  `stale_feed.max_mark_price_age_ms`; opens no network or database client.
- `--healthcheck`: prints one JSON object (mode, Python version, application revision, held,
  stamp age and the latest task results) and exits by the same rules; opens no network or
  database client (OPS-04, D-31).
- `--initialize-gate-state` and `--operator-id`: parsed here, consumed by the start sequence of
  plan 24-26.

Refusals and health output name variables and keys, never values (OPS-02, T-24-29).

The production runner is `production_run_live` (plan 24-27): it assembles the live process with
`build_wiring`, runs the start sequence, waits for SIGTERM or SIGINT and stops in order (scheduler,
bot, stream supervisor, queued stream writes, `ExecutionService.drain()`, `StoreExecutor.close()`).
A start the sequence refuses, or a wiring with a broken link, is reported with its step and code
(`--hold-on-refusal` then holds instead of exiting).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
import threading
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

from src.adapters.code_version import (
    BUILD_REVISION_VARIABLE,
    BuildRevisionError,
    CodeVersionError,
    read_build_revision,
    read_code_version,
)
from src.execution.execution_limits import ExecutionLimitsInvalid, load_execution_limits
from src.live.config import (
    ACCEPTED_MODES,
    DEFAULT_STATE_DIR,
    MODE_VARIABLE,
    UNRESOLVED_MODE,
    LiveConfig,
    LiveExitCode,
    LiveLivenessUnreadable,
    LiveRefusal,
    default_limits_path,
    live_liveness_problem,
    parse_live_environment,
    read_live_liveness,
    remove_live_liveness,
)
from src.ops.redaction import configure_logging
from src.paper import held_marker

REPO_ROOT = Path(__file__).resolve().parents[2]
UNKNOWN_REVISION = "unknown"


@dataclass(frozen=True)
class LiveContext:
    """What the production runner receives once the process has been admitted."""

    config: LiveConfig
    env: Mapping[str, str]
    clock: Callable[[], datetime]
    started_at_utc: datetime
    initialize_gate_state: bool
    operator_id: str | None
    # Plan 24-27: `--hold-on-refusal` and an injected stop wait (None = install signal handlers).
    hold_on_refusal: bool = False
    wait_for_stop: Callable[[], None] | None = None


LiveRunner = Callable[[LiveContext], int]


def build_parser() -> argparse.ArgumentParser:
    """The command line of the live process (the compose command and the probes parse it)."""
    parser = argparse.ArgumentParser(
        prog="python -m src.live.runtime",
        description="Live runtime: explicit mode, admission, then the Demo execution path.",
    )
    parser.add_argument(
        "--hold-on-refusal",
        action="store_true",
        help=(
            "On a refusal, log it, write the held marker and stay up, non-operational, until "
            "SIGTERM or SIGINT instead of exiting, so a restart policy cannot loop on it."
        ),
    )
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help=(
            "Container probe: print one JSON object (mode, python_version, app_revision, held, "
            "liveness_age_ms, tasks) and exit with status zero only while the process is live. "
            "Opens no network or database client."
        ),
    )
    parser.add_argument(
        "--liveness",
        action="store_true",
        help=(
            "Heartbeat probe: print live and exit with status zero only with no held marker and "
            "a liveness stamp younger than stale_feed.max_mark_price_age_ms; otherwise print "
            "not live and a reason and exit with status one. Opens no network or database client."
        ),
    )
    parser.add_argument(
        "--initialize-gate-state",
        action="store_true",
        help="First-install flag: create the REST gate state file (consumed by plan 24-26).",
    )
    parser.add_argument(
        "--operator-id",
        default=None,
        help="Operator id recorded with --initialize-gate-state (consumed by plan 24-26).",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=DEFAULT_STATE_DIR,
        help=(
            f"Directory of the held marker, liveness stamp, gate state and spill "
            f"(default: {DEFAULT_STATE_DIR.as_posix()})."
        ),
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


def diagnostic_payload(
    environ: Mapping[str, str] | None = None,
    *,
    repo_root: Path = REPO_ROOT,
    version_reader: Callable[[Path], Any] | None = None,
) -> dict[str, str]:
    """The Python version and the application revision for every health answer (OPS-04, D-31).

    The revision is the build stamp `TRADING_APP_REVISION` (40 lowercase hex). Only when the stamp
    is absent does a dev checkout fall back to `read_code_version`; without git the answer is the
    literal `unknown`. A malformed stamp gives `unknown` plus `app_revision_problem`, which names
    the variable and never echoes the value. This function never raises.
    """
    env: Mapping[str, str] = os.environ if environ is None else environ
    payload: dict[str, str] = {"python_version": sys.version}
    try:
        stamped = read_build_revision(env)
    except BuildRevisionError as exc:
        payload["app_revision"] = UNKNOWN_REVISION
        payload["app_revision_problem"] = str(exc)
        return payload
    if stamped is not None:
        payload["app_revision"] = stamped
        return payload
    try:
        reader = version_reader if version_reader is not None else read_code_version
        payload["app_revision"] = str(reader(repo_root).text)
    except (CodeVersionError, OSError):
        payload["app_revision"] = UNKNOWN_REVISION
    return payload


def _hold(
    code: LiveExitCode,
    refusal: str,
    *,
    wait_for_stop: Callable[[], None],
    marker_dir: Path,
) -> int:
    """Hold a refused start: write the held marker, wait for the stop, remove the marker.

    A hold whose marker cannot be written is never entered (without the marker the probe could
    read an earlier run's fresh stamp as healthy): the process exits with the refusal code.
    """
    try:
        held_marker.write_marker(marker_dir, code=int(code), refusal=refusal)
    except OSError as exc:
        print(
            f"live runtime cannot write its held marker ({type(exc).__name__}); exiting with "
            f"{int(code)} instead of holding, because a hold without the marker could look healthy",
            file=sys.stderr,
        )
        structlog.get_logger().error(
            "live runtime held marker not written", refusal=refusal, exit_code=int(code)
        )
        return int(code)
    structlog.get_logger().warning("live runtime held", refusal=refusal, exit_code=int(code))
    try:
        wait_for_stop()
    finally:
        try:
            held_marker.remove_marker(marker_dir)
        except OSError as exc:
            structlog.get_logger().error(
                "live runtime held marker not removed", error=type(exc).__name__
            )
    return int(code)


def _refuse(
    code: LiveExitCode,
    reason: str,
    *,
    mode_label: str,
    hold: bool,
    wait_for_stop: Callable[[], None],
    marker_dir: Path,
) -> int:
    """Report a refusal on stderr and in the log (mode included); hold when asked to."""
    print(f"live runtime refused (exit {int(code)}, mode {mode_label}): {reason}", file=sys.stderr)
    structlog.get_logger().error(
        "live runtime refused", exit_code=int(code), mode=mode_label, reason=reason
    )
    if not hold:
        return int(code)
    return _hold(code, code.name, wait_for_stop=wait_for_stop, marker_dir=marker_dir)


def _mode_label(env: Mapping[str, str]) -> str:
    raw = env.get(MODE_VARIABLE)
    return raw if raw is not None and raw in ACCEPTED_MODES else UNRESOLVED_MODE


def _stale_bound_ms(limits_path: Path) -> tuple[int | None, str | None]:
    """`(bound, None)` or `(None, reason)`; the bound is stale_feed.max_mark_price_age_ms."""
    try:
        limits = load_execution_limits(limits_path)
    except ExecutionLimitsInvalid as exc:
        return None, str(exc)
    bound = limits.stale_feed_max_mark_price_age_ms
    if bound is None:
        return None, "stale_feed.max_mark_price_age_ms is NOT_CONFIGURED"
    return bound, None


def _liveness(
    *, env: Mapping[str, str], state_dir: Path, limits_path: Path, now: Callable[[], datetime]
) -> int:
    """The heartbeat probe: 0 only for no held marker and a fresh liveness stamp."""

    def not_live(reason: str) -> int:
        print(f"not live: {reason}")
        return 1

    bound, why = _stale_bound_ms(limits_path)
    if bound is None:
        return not_live(why or "no liveness bound")
    problem = live_liveness_problem(state_dir, now_utc=now(), bound_ms=bound)
    if problem is not None:
        return not_live(problem)
    print("live")
    return 0


def _healthcheck(
    *,
    env: Mapping[str, str],
    state_dir: Path,
    limits_path: Path,
    repo_root: Path,
    now: Callable[[], datetime],
) -> int:
    """The container probe: one JSON object, exit 0 only while the process is live."""
    payload: dict[str, Any] = {
        "mode": _mode_label(env),
        **diagnostic_payload(env, repo_root=repo_root),
    }
    held = None
    try:
        held = held_marker.read_own_marker(state_dir)
    except OSError:
        payload["held_marker_unreadable"] = True
    payload["held"] = held is not None or payload.get("held_marker_unreadable", False)
    if held is not None:
        payload["held_refusal"] = held.refusal
    age_ms: int | None = None
    tasks: dict[str, str] = {}
    try:
        stamp = read_live_liveness(state_dir)
    except LiveLivenessUnreadable:
        stamp = None
    if stamp is not None:
        age_ms = (now() - stamp.loop_alive_utc) // timedelta(milliseconds=1)
        tasks = dict(stamp.tasks)
    payload["liveness_age_ms"] = age_ms
    payload["tasks"] = tasks
    bound, why = _stale_bound_ms(limits_path)
    problem = why
    if bound is not None:
        problem = live_liveness_problem(state_dir, now_utc=now(), bound_ms=bound)
    payload["healthy"] = problem is None
    payload["problem"] = problem
    print(json.dumps(payload, sort_keys=True))
    return 0 if problem is None else 1


def _usage_error(message: str) -> int:
    print(f"live runtime usage error (exit {int(LiveExitCode.USAGE)}): {message}", file=sys.stderr)
    return int(LiveExitCode.USAGE)


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    wait_for_stop: Callable[[], None] | None = None,
    clock: Callable[[], datetime] | None = None,
    run_live: LiveRunner | None = None,
    repo_root: Path | None = None,
    limits_path: Path | None = None,
) -> int:
    """Run the live process: probes, admission, then the production runner.

    The keyword parameters are test and composition seams; production passes only `run_live`
    (plan 24-27). Every refusal prints its mode and names variables or keys, never values.
    """
    args = build_parser().parse_args(argv)
    env: Mapping[str, str] = os.environ if environ is None else environ
    configure_logging(env)
    stopper = wait_for_stop if wait_for_stop is not None else wait_for_stop_signal
    now = clock if clock is not None else _utc_now
    root = repo_root if repo_root is not None else REPO_ROOT
    limits_file = limits_path if limits_path is not None else default_limits_path(root)
    state_dir: Path = args.state_dir
    hold: bool = args.hold_on_refusal

    if args.liveness and args.healthcheck:
        return _usage_error("--liveness and --healthcheck are separate probes")
    if args.liveness:
        return _liveness(env=env, state_dir=state_dir, limits_path=limits_file, now=now)
    if args.healthcheck:
        return _healthcheck(
            env=env, state_dir=state_dir, limits_path=limits_file, repo_root=root, now=now
        )

    def refuse(code: LiveExitCode, reason: str, mode_label: str) -> int:
        return _refuse(
            code,
            reason,
            mode_label=mode_label,
            hold=hold,
            wait_for_stop=stopper,
            marker_dir=state_dir,
        )

    try:
        config = parse_live_environment(
            env, repo_root=root, limits_path=limits_file, state_dir=state_dir
        )
    except LiveRefusal as refusal:
        return refuse(refusal.code, refusal.reason, refusal.mode_label)

    runner = run_live if run_live is not None else production_run_live
    context = LiveContext(
        config=config,
        env=env,
        clock=now,
        started_at_utc=now(),
        initialize_gate_state=args.initialize_gate_state,
        operator_id=args.operator_id,
        hold_on_refusal=hold,
        wait_for_stop=wait_for_stop,
    )
    try:
        return runner(context)
    except Exception as exc:  # the runner failed: fail closed, name the class only
        print(
            f"live runtime failed (exit {int(LiveExitCode.STARTUP_FAILED)}, mode "
            f"{config.mode.value}): {type(exc).__name__}",
            file=sys.stderr,
        )
        structlog.get_logger().error(
            "live runtime failed", mode=config.mode.value, error=type(exc).__name__
        )
        return int(LiveExitCode.STARTUP_FAILED)


# --------------------------------------------------------------------------- #
# The production runner (plan 24-27; D-01, D-03).
# --------------------------------------------------------------------------- #

DATABASE_URL_VARIABLES = ("DATABASE_URL_SYNC", "DATABASE_URL")
BINANCE_LIMITS_RELATIVE = Path("config") / "binance" / "binance-limits-v1.toml"
STRATEGY_ID = "trend-pullback"
PARAMETER_SET_ID = "baseline-v5"
DEMO_SYMBOLS = ("BTCUSDT",)


class DatabaseUrlMissing(Exception):  # noqa: N818 - a refusal of the start, not an error family
    """Neither DATABASE_URL_SYNC nor DATABASE_URL is set (names the variables, never a value)."""


AssembleFn = Callable[[LiveContext], Any]


def _sqlalchemy_url(database_url: str) -> Any:
    """SQLAlchemy URL object; a bare ``postgresql://`` gets the psycopg 3 driver."""
    from sqlalchemy.engine import make_url

    url = make_url(database_url)
    if url.drivername in ("postgresql", "postgres"):
        url = url.set(drivername="postgresql+psycopg")
    return url


def default_assemble(
    context: LiveContext,
    *,
    repo_root: Path = REPO_ROOT,
    sdk_factory: Callable[..., Any] | None = None,
) -> Any:
    """Build the live process for real: PostgreSQL engine, SDK, PTB application, parameter set.

    `sdk_factory` is None in production (the official SDK client of the mode's environment);
    the Demo smoke (`scripts/demo_rehearsal.py`, plan 24-29) passes a factory that re-checks the
    Demo host.

    Raises:
        DatabaseUrlMissing: no database URL variable is set.
    """
    from sqlalchemy import create_engine

    from src.adapters.binance_limits import load_binance_limits
    from src.domain.registry import load_parameter_set
    from src.live.wiring import build_wiring
    from src.live.wiring_parts import LiveBotProxy

    url = next((context.env[n] for n in DATABASE_URL_VARIABLES if context.env.get(n)), None)
    if url is None:
        raise DatabaseUrlMissing(" or ".join(DATABASE_URL_VARIABLES))
    config = context.config
    token = config.telegram_bot_token

    def application_factory() -> Any:
        from telegram.ext import ApplicationBuilder

        return ApplicationBuilder().token(token).build()

    return build_wiring(
        config=config,
        execution_limits=config.limits,
        binance_limits=load_binance_limits(repo_root / BINANCE_LIMITS_RELATIVE),
        parameter_set=load_parameter_set(STRATEGY_ID, PARAMETER_SET_ID),
        clock=context.clock,
        sleep=asyncio.sleep,
        sdk_factory=sdk_factory,
        application_factory=application_factory,
        bot=LiveBotProxy(),
        engine=create_engine(_sqlalchemy_url(url), pool_pre_ping=True),
        repo_root=repo_root,
        symbols=DEMO_SYMBOLS,
        session_id=context.started_at_utc.strftime("%Y%m%dT%H%M%SZ"),
    )


@dataclass(frozen=True)
class _RunResult:
    """What the async run came to: an exit code, and a refusal reason when it did not run."""

    code: LiveExitCode
    reason: str | None = None


def _install_stop_handlers() -> Callable[[], None]:
    """Install SIGINT and SIGTERM handlers in THIS (the main) thread; return the blocking wait."""
    stop = threading.Event()

    def _handler(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)

    def wait() -> None:
        stop.wait()

    return wait


async def shutdown_in_order(assembly: Any) -> list[str]:
    """Stop the live process in order; returns the names of the steps that failed.

    scheduler, Telegram bot, stream supervisor, queued stream writes, the execution service
    (every outstanding placement completes, none is cancelled mid-send), then the store executor
    (every queued write completes). A step that raises is logged by class name and the next one
    still runs. Safe to call on an assembly that never completed.
    """
    failed: list[str] = []

    async def step(name: str, call: Callable[[], Awaitable[Any]]) -> None:
        try:
            await call()
        except Exception as exc:  # noqa: BLE001 - shutdown goes on, the class name is kept
            failed.append(name)
            structlog.get_logger().error(
                "live shutdown step failed", step=name, error=type(exc).__name__
            )

    if assembly.is_complete:
        wiring = assembly.wiring
        wiring.scheduler.stop()
        task = assembly.scheduler_task
        if task is not None:
            await step("scheduler", lambda: asyncio.shield(task))
        await step("bot", wiring.runner.stop)
        await step("supervisor", lambda: wiring.stream.supervisor.stop(close_listen_key=True))
        await step("stream_writes", wiring.stream.fanout.drain)
        await step("persistence", wiring.persistence.drain)
        await step("service", wiring.service.drain)
        try:
            remove_live_liveness(assembly.config.liveness_dir)
        except OSError as exc:
            structlog.get_logger().warning(
                "live liveness stamp not removed", error=type(exc).__name__
            )
    await step("executor", assembly.executor.aclose)
    return failed


async def _run_async(
    context: LiveContext, assembly: Any, wait_for_stop: Callable[[], None]
) -> _RunResult:
    from src.live.startup import run_start_sequence
    from src.live.wiring import check_wiring

    ports = assembly.startup_ports(
        initialize_gate_state=context.initialize_gate_state, operator_id=context.operator_id
    )
    try:
        outcome = await run_start_sequence(ports, now_utc=context.clock())
    except Exception as exc:  # noqa: BLE001 - fail closed, name the class only
        await shutdown_in_order(assembly)
        return _RunResult(
            LiveExitCode.STARTUP_FAILED, f"the start sequence failed ({type(exc).__name__})"
        )
    if not outcome.admitted:
        reason = f"held at step {outcome.held_step} ({outcome.held_code}): {outcome.held_message}"
        if assembly.broken_links:
            reason += f"; broken links: {', '.join(assembly.broken_links)}"
        await shutdown_in_order(assembly)
        return _RunResult(LiveExitCode.STARTUP_FAILED, reason)
    broken = check_wiring(assembly.wiring)
    if broken:
        await shutdown_in_order(assembly)
        return _RunResult(LiveExitCode.STARTUP_FAILED, f"broken wiring links: {', '.join(broken)}")

    loop = asyncio.get_running_loop()
    stopped = asyncio.Event()

    def wait_then_set() -> None:
        wait_for_stop()
        loop.call_soon_threadsafe(stopped.set)

    threading.Thread(target=wait_then_set, name="live-stop-wait", daemon=True).start()
    stop_waiter = asyncio.ensure_future(stopped.wait())
    waiters: set[asyncio.Future[Any]] = {stop_waiter}
    if assembly.scheduler_task is not None:
        waiters.add(assembly.scheduler_task)
    await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
    stop_waiter.cancel()
    scheduler_ended = assembly.scheduler_task is not None and assembly.scheduler_task.done()
    stop_requested = stopped.is_set()
    await shutdown_in_order(assembly)
    if scheduler_ended and not stop_requested:
        return _RunResult(LiveExitCode.STARTUP_FAILED, "the scheduler ended before a stop signal")
    return _RunResult(LiveExitCode.OK)


def run_admitted(context: LiveContext, *, assemble: AssembleFn | None = None) -> int:
    """Run an admitted live process until a stop signal, then stop it in order (D-01, D-03).

    `assemble(context)` builds the `LiveAssembly` (default: `default_assemble`, the real
    PostgreSQL, SDK and PTB objects). A refusal of the start is printed with its step and code and
    held when `--hold-on-refusal` was given (nothing is running then).
    """
    mode = context.config.mode.value
    marker_dir = context.config.held_marker_dir
    waiter = context.wait_for_stop

    def stopper() -> None:
        if waiter is not None:
            waiter()
        else:
            wait_for_stop_signal()

    def refuse(code: LiveExitCode, reason: str) -> int:
        return _refuse(
            code,
            reason,
            mode_label=mode,
            hold=context.hold_on_refusal,
            wait_for_stop=stopper,
            marker_dir=marker_dir,
        )

    build = assemble if assemble is not None else default_assemble
    try:
        assembly = build(context)
    except DatabaseUrlMissing as exc:
        return refuse(LiveExitCode.STARTUP_FAILED, f"{exc} is not set")
    except Exception as exc:  # noqa: BLE001 - fail closed, name the class only
        return refuse(
            LiveExitCode.STARTUP_FAILED,
            f"the live process could not be built ({type(exc).__name__})",
        )
    run_wait = waiter if waiter is not None else _install_stop_handlers()
    try:
        result = asyncio.run(_run_async(context, assembly, run_wait))
    except Exception as exc:  # noqa: BLE001 - fail closed, name the class only
        return refuse(
            LiveExitCode.STARTUP_FAILED, f"the live process failed ({type(exc).__name__})"
        )
    if result.code is LiveExitCode.OK:
        return int(LiveExitCode.OK)
    return refuse(result.code, result.reason or "the live process stopped")


def production_run_live(context: LiveContext) -> int:
    """The default `LiveRunner` of `main`: assemble for real and run (plan 24-27)."""
    return run_admitted(context)


__all__ = [
    "BUILD_REVISION_VARIABLE",
    "DATABASE_URL_VARIABLES",
    "DatabaseUrlMissing",
    "LiveContext",
    "LiveRunner",
    "build_parser",
    "default_assemble",
    "diagnostic_payload",
    "main",
    "production_run_live",
    "run_admitted",
    "shutdown_in_order",
    "wait_for_stop_signal",
]


if __name__ == "__main__":
    raise SystemExit(main())
