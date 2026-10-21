"""Operator commands for the persisted REST gate state (plan 20-07, Task 4; owner decision O-C).

    python -m src.ops.rest_gate_cli status --path STATE_FILE
    python -m src.ops.rest_gate_cli clear --path STATE_FILE --operator-id ID --reason TEXT
        [--force]

`status` is read-only: it prints what the state file holds and the recovery status the gate
would report after a restart. `clear` writes a fresh valid initialized record with no deadline
(the same shape `FileGateStateStore.initialize` writes) and keeps the old file aside; it is the
way to lift a false restriction (a ban the owner finds was wrongly assumed, or a lost or corrupt
file) without waiting. It takes effect only at the NEXT restart of the trading process, through
`RestRateLimitGate.restore()`: nothing here touches a running gate. A persisted ban or pause
deadline that is still in the future is refused unless `--force` is given.

The operator id is audit metadata, not authentication: ssh access to the host is the access
control until the remote operator interface of Phase 23/24. The commands never call Binance,
never read `.env` or any environment value, and print no secret. The library functions
(`status_report`, `clear_state`) take the time as an argument; only `main` reads the clock, once.

Exit codes: 0 done; 2 usage error, or `status` found the file missing, corrupt or unreadable;
3 `clear` refused a future deadline without `--force`; 4 `clear` could not write (the old file
is untouched).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import structlog

from src.adapters.binance_ratelimit_gate import GateRecoveryStatus, GateStateRecord
from src.ops.rest_gate_state import FileGateStateStore, GateStateInspection

log = structlog.get_logger()

EXIT_OK = 0
EXIT_REFUSED_OR_UNREADABLE = 2
EXIT_FUTURE_DEADLINE = 3
EXIT_WRITE_FAILED = 4

REMINDER = (
    "A recorded deadline cannot tell a real Binance ban from the assumed wait; "
    "check once by hand before clearing"
)
_STOP_FIRST = (
    "Stop the trading process before clearing: a running process can write its in-memory "
    "deadlines back over the cleared file, and a failed save in the running process hides its "
    "deadlines from this command, so the check-by-hand reminder applies even when no deadline "
    "is shown."
)


@dataclass(frozen=True, slots=True)
class CliResult:
    """What a command prints (`lines`, one per output line) and its exit code."""

    exit_code: int
    lines: tuple[str, ...]


def _utc_text(value: datetime | None) -> str:
    if value is None:
        return "none"
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _status_after_restart(inspection: GateStateInspection) -> GateRecoveryStatus:
    """The status a gate would report after a restart, from the record alone."""
    if inspection.record is None:
        return GateRecoveryStatus.RESTORED_UNKNOWN_STATE
    return GateRecoveryStatus.RESTORED_DURABLE


def _future_deadlines(record: GateStateRecord | None, now_utc: datetime) -> list[str]:
    if record is None:
        return []
    found: list[str] = []
    if record.ban_until_utc is not None and record.ban_until_utc > now_utc:
        found.append(f"ban_until_utc {_utc_text(record.ban_until_utc)}")
    if record.pause_until_utc is not None and record.pause_until_utc > now_utc:
        found.append(f"pause_until_utc {_utc_text(record.pause_until_utc)}")
    return found


def status_report(store: FileGateStateStore, now_utc: datetime) -> CliResult:
    """Describe the state file. Read-only: nothing is written, renamed or moved."""
    lines = [f"state file: {store.path}"]
    try:
        inspection = store.inspect()
    except OSError as exc:
        log.warning("rest_gate_cli.status_unreadable", error_type=type(exc).__name__)
        lines += ["file: unreadable (I/O error)", REMINDER]
        return CliResult(EXIT_REFUSED_OR_UNREADABLE, tuple(lines))
    record = inspection.record
    if not inspection.exists:
        lines.append("file: missing (a lost file reads as loss of initialized state)")
    elif inspection.corrupt:
        lines.append("file: corrupt (does not parse; it is set aside at the next start)")
    elif record is not None:
        lines += [
            "file: present and valid",
            f"initialized: yes, at {_utc_text(record.initialized_at_utc)}"
            f" by {record.initialized_by}",
            f"ban_until_utc: {_utc_text(record.ban_until_utc)}",
            f"pause_until_utc: {_utc_text(record.pause_until_utc)}",
            f"recorded_at_utc: {_utc_text(record.recorded_at_utc)}",
            f"future deadline at {_utc_text(now_utc)}: "
            + (", ".join(_future_deadlines(record, now_utc)) or "none"),
        ]
    lines.append(f"recovery status after a restart: {_status_after_restart(inspection).value}")
    if record is None:
        lines.append("every start stays blocked (no end) until `clear` writes a valid record")
    lines.append(REMINDER)
    log.info("rest_gate_cli.status", exists=inspection.exists, corrupt=inspection.corrupt)
    return CliResult(EXIT_OK if record is not None else EXIT_REFUSED_OR_UNREADABLE, tuple(lines))


def clear_state(
    store: FileGateStateStore,
    now_utc: datetime,
    operator_id: str,
    reason: str,
    force: bool,
) -> CliResult:
    """Write a fresh valid initialized record; it takes effect at the next restart."""
    operator = operator_id.strip()
    why = reason.strip()
    if not operator or not why:
        return CliResult(
            EXIT_REFUSED_OR_UNREADABLE,
            ("refused: --operator-id and --reason must both be non-empty",),
        )
    try:
        inspection = store.inspect()
    except OSError as exc:
        log.warning("rest_gate_cli.clear_unreadable", error_type=type(exc).__name__)
        return CliResult(
            EXIT_WRITE_FAILED, ("failed: the state file could not be read; nothing was changed",)
        )
    future = _future_deadlines(inspection.record, now_utc)
    if future and not force:
        log.warning("rest_gate_cli.clear_refused", operator_id=operator, deadlines=future)
        return CliResult(
            EXIT_FUTURE_DEADLINE,
            (
                "refused: a persisted deadline is still in the future: " + ", ".join(future),
                "Use --force together with --reason if you have checked by hand that it is false.",
                REMINDER,
            ),
        )
    forced = bool(future)
    aside_kind = "corrupt" if inspection.corrupt else "replaced"
    try:
        store.reinitialize(now_utc=now_utc, operator_id=operator, aside_kind=aside_kind)
    except (OSError, ValueError) as exc:
        log.error("rest_gate_cli.clear_failed", operator_id=operator, error_type=type(exc).__name__)
        return CliResult(
            EXIT_WRITE_FAILED,
            ("failed: the new state could not be written; the old file is untouched",),
        )
    log.info(
        "rest_gate_cli.clear",
        operator_id=operator,
        reason=why,
        forced=forced,
        previous=("corrupt" if inspection.corrupt else "valid" if inspection.exists else "missing"),
    )
    lines = [
        f"cleared: {store.path} now holds a fresh initialized record (by {operator})"
        + (" [forced]" if forced else ""),
    ]
    if inspection.exists:
        lines.append(f"the previous file was kept aside as '*.{aside_kind}-<UTC time>'")
    lines += [
        "This takes effect at the next restart of the trading process, through restore().",
        _STOP_FIRST,
        REMINDER,
    ]
    if forced:
        lines.insert(1, f"forced over: {', '.join(future)}")
    return CliResult(EXIT_OK, tuple(lines))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.ops.rest_gate_cli",
        description="Inspect or clear the persisted REST gate state (takes effect at restart).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="print the persisted gate state (read-only)")
    status.add_argument("--path", required=True, type=Path, help="the gate state file")
    clear = sub.add_parser("clear", help="write a fresh valid record (effective at next restart)")
    clear.add_argument("--path", required=True, type=Path, help="the gate state file")
    clear.add_argument("--operator-id", required=True, help="audit metadata, not authentication")
    clear.add_argument("--reason", required=True, help="why the state is cleared")
    clear.add_argument(
        "--force", action="store_true", help="clear even if a persisted deadline is in the future"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point: the only place that reads the clock (once)."""
    args = _parser().parse_args(argv)
    now_utc = datetime.now(UTC)
    store = FileGateStateStore(args.path, clock=lambda: now_utc)
    if args.command == "status":
        result = status_report(store, now_utc)
    else:
        result = clear_state(store, now_utc, args.operator_id, args.reason, args.force)
    stream = (
        sys.stderr if result.exit_code in (EXIT_FUTURE_DEADLINE, EXIT_WRITE_FAILED) else sys.stdout
    )
    for line in result.lines:
        print(line, file=stream)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
