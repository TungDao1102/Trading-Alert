"""The paper process entrypoint: `python -m src.paper.runtime` (plan 16-22, D-01, L-05, D061 E).

Order of `main` (each step may end the process before the next one runs):

1. Configure redacted logging.
2. Trade-key refusal: any `BINANCE_*` name in the environment exits 3 (names only are printed).
3. Start gate: the approved allowlist is read through the freeze accessors only. An empty
   allowlist logs "SKIPPED (allowlist empty)" and exits 0, before any adapter, database engine
   or Telegram application is constructed, and with no fallback to any set.
4. Admission (the user's decision Q-A, `runtime-exact-hash-all`): the runtime process gate
   requires an exact-hash allowlist entry for EVERY parameter set, a fully rationalized one
   included. It runs before any candle is parsed and before `pin_stream_epoch`. A missing entry
   or a hash that differs from the registry file's hash exits 6. A match only lets the existing
   validation continue; `pin_stream_epoch` (unchanged) still judges the set afterwards.
5. The ratified runtime configuration (exit 4 when anything is absent).
6. The epoch: pinned only on the explicit operator flag `--pin-epoch` when no pinned state
   exists; every restart loads the stored epoch and never mints one (exit 5 without a pin,
   exit 6 on any mismatch).
7. RUNTIME_START, the run, RUNTIME_STOP (recorded only on a clean stop, so a crash leaves a
   START without a STOP, which the coverage code reads as a crash).

Two layers, deliberately different (see config/paper/README.md): the runtime process gate here
(exact-hash authorization for every set) and the per-call rule inside `pin_stream_epoch` (an
entry is required only for a set without rationale tables). Rationale tables never replace
runtime authorization.

Exit codes are the named table `ExitCode` in `src/paper/runtime_config.py`. With the opt-in
flag `--hold-on-refusal` (used by the compose service) a refusal does not exit: the process logs
it, stays up and returns the refusal code only after SIGTERM or SIGINT, so a restart policy can
never loop on a refusal. SKIPPED and restartable failures are never held.

The live loop is plan 16-26. Until it exists the `run_loop` seam defaults to waiting for the
stop signal.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import structlog

from src.ops.redaction import configure_logging
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
from src.paper.runtime_config import (
    ConfigNotRatified,
    ExitCode,
    RuntimeConfig,
    load_runtime_config,
    read_env,
    refuse_trade_capable_env,
)
from src.paper.runtime_state import RuntimeRecord, RuntimeRecordConflict, RuntimeStatePort
from src.paper.vocabulary import RuntimeEventType
from src.persistence.errors import PersistenceError

SKIPPED_EVENT = "SKIPPED (allowlist empty)"
DEFAULT_PINNED_STATE = Path("logs/paper/pinned_epoch.json")


@dataclass(frozen=True)
class RuntimeContext:
    """What the run (plan 16-26) receives once the process has been admitted and started."""

    epoch: StreamEpoch
    config: RuntimeConfig
    state: RuntimeStatePort
    env: Mapping[str, str]
    clock: Callable[[], datetime]
    registry_root: Path | None


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
            "On a refusal (exit codes 3 to 6) log it and stay up until SIGTERM or SIGINT "
            "instead of exiting, so a restart policy cannot loop on it."
        ),
    )
    parser.add_argument(
        "--pin-epoch",
        action="store_true",
        help=(
            "Operator command: pin the epoch of this trial when no pinned state exists. "
            "Without it a start needs an existing pinned state and reuses its epoch."
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


def _refuse(
    code: ExitCode,
    reason: str,
    *,
    hold: bool,
    wait_for_stop: Callable[[], None],
) -> int:
    """Report a refusal on stderr and in the log; hold until stopped when asked to."""
    print(f"paper runtime refused (exit {int(code)}): {reason}", file=sys.stderr)
    structlog.get_logger().error("paper runtime refused", exit_code=int(code), reason=reason)
    if hold:
        wait_for_stop()
    return int(code)


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


def _state_from_env(values: Mapping[str, str]) -> RuntimeStatePort:
    """The production state port: journal rows on PostgreSQL (Q-J), never an in-memory fallback."""
    url = values.get("DATABASE_URL_SYNC") or values.get("DATABASE_URL")
    if not url:
        raise ConfigNotRatified(["DATABASE_URL_SYNC or DATABASE_URL"])
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    # Imported here so that a SKIPPED start and every refusal never import SQLAlchemy.
    from sqlalchemy import create_engine

    from src.persistence.paper_runtime_state import PgRuntimeState
    from src.persistence.uow import OperationalDatabase

    return PgRuntimeState(OperationalDatabase(create_engine(url, future=True)))


def _epoch_record(event_type: RuntimeEventType, epoch: StreamEpoch, at: datetime) -> RuntimeRecord:
    return RuntimeRecord(
        event_type=event_type,
        epoch_id=epoch.epoch_id,
        occurred_at_utc=at,
        payload={
            "strategy_id": epoch.strategy_id,
            "parameter_set_id": epoch.parameter_set_id,
            "parameter_set_hash": epoch.parameter_set_hash,
        },
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    wait_for_stop: Callable[[], None] | None = None,
    state: RuntimeStatePort | None = None,
    registry_root: Path | None = None,
    clock: Callable[[], datetime] | None = None,
    run_loop: Callable[[RuntimeContext], None] | None = None,
) -> int:
    """Run the paper process: start gate, admission, epoch, run; returns the exit status.

    The keyword parameters are test and composition seams; production passes none of them.
    """
    args = build_parser().parse_args(argv)
    env: Mapping[str, str] = os.environ if environ is None else environ
    configure_logging(env)
    stopper = wait_for_stop if wait_for_stop is not None else wait_for_stop_signal
    now = clock if clock is not None else _utc_now
    hold: bool = args.hold_on_refusal

    def refuse(code: ExitCode, reason: str) -> int:
        return _refuse(code, reason, hold=hold, wait_for_stop=stopper)

    trade_names = refuse_trade_capable_env(env)
    if trade_names:
        return refuse(
            ExitCode.TRADE_KEY_REFUSED,
            "trade-capable variable present: " + ", ".join(trade_names),
        )

    if not allowlist_entries():
        structlog.get_logger().info(SKIPPED_EVENT)
        return int(ExitCode.OK)

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
        config = load_runtime_config(values.get("PAPER_RUNTIME_CONFIG"))
        port = state if state is not None else _state_from_env(values)
    except ConfigNotRatified as exc:
        return refuse(ExitCode.CONFIG_NOT_RATIFIED, str(exc))

    pinned_path: Path = args.pinned_state
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
        newly_pinned = True
    else:
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
        newly_pinned = False

    context = RuntimeContext(
        epoch=epoch,
        config=config,
        state=port,
        env=values,
        clock=now,
        registry_root=registry_root,
    )
    try:
        if newly_pinned:
            # Recorded before the file is written: a failed write leaves an orphan record of an
            # epoch no run uses, while the reverse order would leave a trial with no pin record.
            port.record(_epoch_record(RuntimeEventType.EPOCH_PINNED, epoch, epoch.opened_at_utc))
            write_pinned_state(epoch, pinned_path)
        port.record(_epoch_record(RuntimeEventType.RUNTIME_START, epoch, now()))
        structlog.get_logger().info("runtime start", epoch_id=epoch.epoch_id)
        if run_loop is not None:
            run_loop(context)
        else:
            stopper()
        port.record(_epoch_record(RuntimeEventType.RUNTIME_STOP, epoch, now()))
    except (PersistenceError, RuntimeRecordConflict) as exc:
        print(
            f"paper runtime failed closed (exit {int(ExitCode.FAIL_CLOSED_RUNTIME)}): "
            f"{type(exc).__name__}",
            file=sys.stderr,
        )
        return int(ExitCode.FAIL_CLOSED_RUNTIME)
    return int(ExitCode.OK)


if __name__ == "__main__":
    raise SystemExit(main())
