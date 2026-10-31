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

Refusals and health output name variables and keys, never values (OPS-02, T-24-29). Until plan
24-27 composes the production runner, an admitted start refuses with STARTUP_FAILED
"runner not composed" (fail closed).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
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

    if run_live is None:
        return refuse(
            LiveExitCode.STARTUP_FAILED,
            "runner not composed (the production runner is composed by plan 24-27)",
            config.mode.value,
        )
    context = LiveContext(
        config=config,
        env=env,
        clock=now,
        started_at_utc=now(),
        initialize_gate_state=args.initialize_gate_state,
        operator_id=args.operator_id,
    )
    try:
        return run_live(context)
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


__all__ = [
    "BUILD_REVISION_VARIABLE",
    "LiveContext",
    "LiveRunner",
    "build_parser",
    "diagnostic_payload",
    "main",
    "wait_for_stop_signal",
]


if __name__ == "__main__":
    raise SystemExit(main())
