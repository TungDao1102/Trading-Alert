"""S19 REST gate operator commands after a false 418 (plan 25-14; OPS-01, D-06, P20-DEMO).

TEST_ONLY. The procedure of RUNBOOK 22.5 and 21.3, end to end on the real process:

1. A false 418 is INJECTED under the real adapter (`SdkFaults`, D-07: never provoked) with no
   Retry-After, so the real gate takes the ratified fallback wait and persists the ban to its state
   file; the ban alert is journaled.
2. `rest_gate_cli status` (read only) shows the persisted ban while the process still runs, and an
   unforced `clear` is refused for the future deadline without writing anything. This is what the
   run OBSERVES for research assumption A6 (the CLI has no check for a running process; the refusal
   is for the deadline). A forced clear while the process runs is NOT attempted: the procedure stops
   the process first ("a running process can write its in-memory deadlines back over the cleared
   file").
3. The process is stopped in order. `status` shows the ban, an unforced `clear` is refused (exit 3,
   no audit line), `clear --force --operator-id --reason` writes a fresh initialized record and
   appends its audit lines (`requested`, `cleared`) to `<state file>.clear-audit.jsonl`.
4. A second process starts: the gate restores a clear record (RESTORED_DURABLE), the start is
   admitted and enabled, a far request is placed and cancelled, the account ends clean.

The commands run in process through `rest_gate_cli.main(argv)`, never by editing the state file. The
CLI reads the wall clock once; on the twin the gate deadline is virtual time, so the twin hands the
CLI the env clock for that one read (the library functions take the time as an argument). On Demo
the CLI reads the real clock, as on the host.

If a run stops after the injection and before the clear, the state file holds a ban for the real
fallback wait (days): `recovery_instruction` in the evidence names the commands.

Labels: the injection step is `label_for(env, injected=True)`; every other step carries the env
label.
"""

from __future__ import annotations

import contextlib
import io
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest import mock

from scripts import demo_rehearsal as dr
from src.ops import rest_gate_cli

from tests.support.demo_scenarios.harness import ScenarioRecorder, account_clean, ensure_clean_start
from tests.support.demo_scenarios.s04_stop_rejected import record_injection_step, record_step
from tests.support.demo_scenarios.s06_replay import (
    cancel_resting_entry,
    place_approved_entry,
    place_entry_calls,
    shutdown,
    start_evidence,
)
from tests.support.demo_scenarios.s08_stream_loss import card_and_approve, expire_plan
from tests.support.demo_scenarios.s10_rate_limit import (
    REASON_BAN,
    SDK_METHOD,
    await_refusal,
    ban_alerts,
    gate_of,
    persisted_record,
    policy_of,
    read_journal,
)
from tests.support.fault_edge import rate_limit_ban_error

OPERATOR_ID = "phase25-owner"
CLEAR_REASON = "Phase 25 S19 false restriction"
SCENARIO_FAR = "far"
_TOLERANCE_SECONDS = 2

STEP_BASELINE = "gate_open_at_start"
STEP_INJECT = "inject_false_418"
STEP_BAN_PERSISTED = "ban_persisted_and_alerted"
STEP_STATUS_RUNNING = "status_while_the_process_runs"
STEP_STOPPED = "process_stopped_in_order"
STEP_STATUS = "status_shows_the_ban"
STEP_CLEAR_REFUSED = "clear_refuses_the_future_deadline"
STEP_CLEAR = "clear_force_with_operator_and_reason"
STEP_AUDIT = "clear_audit_lines_written"
STEP_STATUS_CLEARED = "status_after_the_clear"
STEP_RESTORED_CLEAR = "restart_restores_a_clear_gate"
STEP_ENTRY_ALLOWED = "request_placed_after_the_clear"

_REFUSAL_TEXT = "a persisted deadline is still in the future"


@dataclass(frozen=True)
class CliRun:
    """What one in-process `rest_gate_cli.main` call returned and printed."""

    exit_code: int
    lines: tuple[str, ...]


def record_inject(env: Any, recorder: ScenarioRecorder, detail: str) -> None:
    """The injected 418: DEMO_FAULT_INJECTED on Demo, never DEMO_OBSERVED."""
    record_injection_step(env, recorder, detail, name=STEP_INJECT)


def record_reaction(env: Any, recorder: ScenarioRecorder, name: str, detail: str) -> None:
    """A reaction of the real process or of the operator command: the env label."""
    record_step(env, recorder, name, detail)


def run_cli(env: Any, argv: list[str]) -> CliRun:
    """Call `rest_gate_cli.main(argv)` in process and capture what it prints.

    On a synthetic env the module's one clock read (`datetime.now`) is replaced by the env clock,
    because the gate deadline of the twin is virtual time. On Demo nothing is replaced.
    """
    out, err = io.StringIO(), io.StringIO()
    patch: Any = contextlib.nullcontext()
    if env.synthetic:
        at = env.clock()

        class _At(datetime):
            @classmethod
            def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
                return at if tz is None else at.astimezone(tz)

        patch = mock.patch.object(rest_gate_cli, "datetime", _At)
    with patch, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = rest_gate_cli.main(argv)
    lines = tuple((out.getvalue() + err.getvalue()).splitlines())
    return CliRun(exit_code=code, lines=lines)


def parse_status(lines: tuple[str, ...]) -> dict[str, str]:
    """The times and the recovery status of a `status` print (no path, nothing else)."""
    keys = {
        "ban_until_utc: ": "ban_until_utc",
        "pause_until_utc: ": "pause_until_utc",
        "recovery status after a restart: ": "recovery_status",
    }
    parsed: dict[str, str] = {}
    for line in lines:
        for prefix, name in keys.items():
            if line.startswith(prefix):
                parsed[name] = line[len(prefix) :]
        if line.startswith("future deadline at "):
            parsed["future_deadline"] = line.split(": ", 1)[1]
    return parsed


def audit_lines(state_path: Path) -> list[dict[str, Any]]:
    """The audit file of the clear command next to the state file (empty when it is absent)."""
    path = state_path.with_name(state_path.name + ".clear-audit.jsonl")
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _cli_args(command: str, state_path: Path, *extra: str) -> list[str]:
    return [command, "--path", str(state_path), *extra]


def _clear_args(state_path: Path, *, force: bool) -> list[str]:
    extra = ["--operator-id", OPERATOR_ID, "--reason", CLEAR_REASON]
    if force:
        extra.append("--force")
    return _cli_args("clear", state_path, *extra)


class _Processes:
    """The process that runs now (a restart replaces it) and whether it was stopped already."""

    def __init__(self, env: Any) -> None:
        self.env = env
        self.stopped = False

    async def stop(self) -> None:
        await shutdown(self.env)
        self.stopped = True

    async def shutdown(self) -> None:
        if not self.stopped:
            await self.stop()


async def run(env: Any, recorder: ScenarioRecorder) -> str:
    """Run S19 on `env`; returns the outcome. A failed step raises `dr.SmokeHalt`."""
    recorder.default_label = env.label
    await ensure_clean_start(env, recorder)
    processes = _Processes(env)
    try:
        return await _sequence(env, recorder, processes)
    finally:
        env.sdk_faults.clear(SDK_METHOD)
        await processes.shutdown()


async def _sequence(env: Any, recorder: ScenarioRecorder, processes: _Processes) -> str:
    start_evidence(env, recorder)
    await dr._bring_up(env, recorder, "start")
    facts: dict[str, Any] = recorder.details.setdefault("rest_gate_cli", {})
    facts["cli_clock"] = "env clock (twin)" if env.synthetic else "wall clock"
    state_path: Path = env.assembly.config.gate_state_path
    gate = gate_of(env)
    if gate.restriction() is not None:
        raise dr._smoke_fail(env, recorder, STEP_BASELINE, "the gate was restricted at the start")
    record_reaction(env, recorder, STEP_BASELINE, "the REST gate holds no restriction at the start")

    first = await _inject_and_persist(env, recorder, facts)
    await _status_while_running(env, recorder, facts, state_path)
    await expire_plan(env, first)

    await processes.stop()
    record_reaction(
        env, recorder, STEP_STOPPED, "the process was stopped in order before the commands (22.5)"
    )
    await _status_and_clear(env, recorder, facts, state_path)
    await _restart_and_place(env, recorder, facts, processes)
    recorder.outcome = dr.OUTCOME_COMPLETE
    return dr.OUTCOME_COMPLETE


async def _inject_and_persist(env: Any, recorder: ScenarioRecorder, facts: dict[str, Any]) -> Any:
    policy = policy_of(env)
    facts["fallback_418_seconds"] = int(policy.no_retry_after_wait_418_seconds)
    facts["recovery_instruction"] = (
        "stop the process, then `python -m src.ops.rest_gate_cli status --path <gate state file>` "
        "and `clear --path <gate state file> --operator-id <id> --reason <text> --force` "
        "(RUNBOOK 21.3) before any other scenario"
    )
    first = await card_and_approve(env, recorder)
    armed_at = env.clock()
    env.sdk_faults.fail_sdk(SDK_METHOD, rate_limit_ban_error(), times=1)
    record_inject(
        env,
        recorder,
        f"a false HTTP 418 with no Retry-After is raised under the real adapter for the next "
        f"{SDK_METHOD} call; nothing is sent to the exchange for it",
    )
    await env.owner.act("confirm", short_id=first.short_id, note="")
    decisions = await await_refusal(env, recorder, first)
    gate = gate_of(env)
    restriction = gate.restriction()
    record = persisted_record(env)
    alerts = await read_journal(env, ban_alerts)
    facts["ban_alerts"] = alerts
    facts["decisions"] = decisions
    facts["place_entry_calls_at_refusal"] = place_entry_calls(env)
    facts["sdk_injected_calls"] = len(
        [c for c in env.sdk_faults.calls_to(SDK_METHOD) if c.get("injected") is True]
    )
    if (
        record is None
        or record.ban_until_utc is None
        or record.ban_until_utc < armed_at
        or len(alerts) != 1
        or alerts[0].get("reason") != REASON_BAN
        or place_entry_calls(env) != 0
        or facts["sdk_injected_calls"] != 1
        or (restriction is None or restriction.reason != REASON_BAN)
        and env.synthetic
    ):
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_BAN_PERSISTED,
            f"ban persisted: {record is not None and record.ban_until_utc is not None}, alerts "
            f"{len(alerts)}, place_entry {place_entry_calls(env)}, "
            f"injected calls {facts['sdk_injected_calls']}",
        )
    wait = int((record.ban_until_utc - record.recorded_at_utc).total_seconds())
    facts["persisted_wait_seconds"] = wait
    if abs(wait - facts["fallback_418_seconds"]) > _TOLERANCE_SECONDS:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_BAN_PERSISTED,
            f"the persisted wait is {wait} s, expected the fallback "
            f"{facts['fallback_418_seconds']}",
        )
    record_reaction(
        env,
        recorder,
        STEP_BAN_PERSISTED,
        f"the gate persisted the ban ({wait} s, the ratified fallback), the ban alert is journaled "
        "and the CONFIRM was refused with nothing sent",
    )
    return first


async def _status_while_running(
    env: Any, recorder: ScenarioRecorder, facts: dict[str, Any], state_path: Path
) -> None:
    """Research assumption A6, observed: `status` and an unforced `clear` while the process runs."""
    status = run_cli(env, _cli_args("status", state_path))
    parsed = parse_status(status.lines)
    facts["status_running"] = {"exit_code": status.exit_code, **parsed}
    before = persisted_record(env)
    attempt = run_cli(env, _clear_args(state_path, force=False))
    after = persisted_record(env)
    refused_for = (
        "future deadline" if any(_REFUSAL_TEXT in line for line in attempt.lines) else "other"
    )
    facts["a6"] = {
        "status_exit_code_while_running": status.exit_code,
        "clear_unforced_exit_code_while_running": attempt.exit_code,
        "refused_for": refused_for,
        "state_unchanged_by_the_refusal": before == after,
        "audit_lines_after_the_refusal": len(audit_lines(state_path)),
        "forced_clear_while_running": "NOT_ATTEMPTED (the procedure stops the process first)",
    }
    ok = (
        status.exit_code == rest_gate_cli.EXIT_OK
        and parsed.get("ban_until_utc", "none") != "none"
        and attempt.exit_code == rest_gate_cli.EXIT_FUTURE_DEADLINE
        and refused_for == "future deadline"
        and before == after
        and not audit_lines(state_path)
    )
    if not ok:
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_STATUS_RUNNING,
            f"status exit {status.exit_code}, unforced clear exit {attempt.exit_code} "
            f"({refused_for}), unchanged {before == after}",
        )
    record_reaction(
        env,
        recorder,
        STEP_STATUS_RUNNING,
        "status (read only) shows the ban while the process runs; an unforced clear is refused "
        "for the future deadline and changes nothing (the CLI has no running-process check)",
    )


async def _status_and_clear(
    env: Any, recorder: ScenarioRecorder, facts: dict[str, Any], state_path: Path
) -> None:
    status = run_cli(env, _cli_args("status", state_path))
    parsed = parse_status(status.lines)
    facts["status_stopped"] = {"exit_code": status.exit_code, **parsed}
    if (
        status.exit_code != rest_gate_cli.EXIT_OK
        or parsed.get("ban_until_utc", "none") == "none"
        or parsed.get("future_deadline", "none") == "none"
    ):
        raise dr._smoke_fail(
            env, recorder, STEP_STATUS, f"status exit {status.exit_code}, shown {parsed}"
        )
    record_reaction(
        env,
        recorder,
        STEP_STATUS,
        "status exits 0 and shows the ban deadline as a future deadline",
    )

    refused = run_cli(env, _clear_args(state_path, force=False))
    facts["clear_unforced"] = {
        "exit_code": refused.exit_code,
        "audit_lines_after": len(audit_lines(state_path)),
    }
    if refused.exit_code != rest_gate_cli.EXIT_FUTURE_DEADLINE or audit_lines(state_path):
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_CLEAR_REFUSED,
            f"unforced clear exit {refused.exit_code}, audit lines {len(audit_lines(state_path))}",
        )
    record_reaction(
        env,
        recorder,
        STEP_CLEAR_REFUSED,
        "clear without --force is refused (exit 3) while the deadline is in the future; "
        "nothing was written",
    )

    cleared = run_cli(env, _clear_args(state_path, force=True))
    facts["clear_forced"] = {"exit_code": cleared.exit_code}
    if cleared.exit_code != rest_gate_cli.EXIT_OK:
        raise dr._smoke_fail(env, recorder, STEP_CLEAR, f"clear --force exited {cleared.exit_code}")
    record_reaction(
        env,
        recorder,
        STEP_CLEAR,
        "clear --force with an operator id and a reason exited 0 and wrote a fresh record",
    )

    lines = audit_lines(state_path)
    outcomes = [str(line.get("outcome")) for line in lines]
    forced = all(line.get("forced") is True for line in lines)
    facts["audit"] = {"lines": len(lines), "outcomes": outcomes, "forced": forced}
    named = all(
        line.get("operator_id") == OPERATOR_ID and line.get("reason") == CLEAR_REASON
        for line in lines
    )
    overridden = all(bool(line.get("overridden")) for line in lines)
    if outcomes != ["requested", "cleared"] or not (forced and named and overridden):
        raise dr._smoke_fail(
            env, recorder, STEP_AUDIT, f"audit lines {outcomes}, forced {forced}, named {named}"
        )
    record_reaction(
        env,
        recorder,
        STEP_AUDIT,
        "the audit file holds a requested and a cleared line with the operator, the reason, "
        "the forced flag and the overridden deadline",
    )

    after = run_cli(env, _cli_args("status", state_path))
    parsed_after = parse_status(after.lines)
    facts["status_cleared"] = {"exit_code": after.exit_code, **parsed_after}
    if (
        after.exit_code != rest_gate_cli.EXIT_OK
        or parsed_after.get("ban_until_utc") != "none"
        or parsed_after.get("future_deadline") != "none"
    ):
        raise dr._smoke_fail(
            env, recorder, STEP_STATUS_CLEARED, f"status after the clear: {parsed_after}"
        )
    record_reaction(
        env, recorder, STEP_STATUS_CLEARED, "status after the clear shows no deadline at all"
    )


async def _restart_and_place(
    env: Any, recorder: ScenarioRecorder, facts: dict[str, Any], processes: _Processes
) -> None:
    if env.restart is None:
        raise dr._smoke_fail(env, recorder, STEP_RESTORED_CLEAR, "no restart is available")
    second = await env.restart()
    processes.env = second
    processes.stopped = False
    await dr._bring_up(second, recorder, "restart")
    gate = gate_of(second)
    status = gate.recovery_status()
    restriction = gate.restriction()
    facts["restart"] = {
        "restriction_after_restart": None if restriction is None else restriction.reason,
        "recovery_status": getattr(status, "value", str(status)),
        "admitted_and_enabled": True,
    }
    if restriction is not None or facts["restart"]["recovery_status"] != "RESTORED_DURABLE":
        raise dr._smoke_fail(
            env, recorder, STEP_RESTORED_CLEAR, f"the restarted gate reports {facts['restart']}"
        )
    record_reaction(
        env,
        recorder,
        STEP_RESTORED_CLEAR,
        "the second process restored a clear gate (RESTORED_DURABLE) and was enabled",
    )
    sent_before = place_entry_calls(second)
    placed = await place_approved_entry(second, recorder, SCENARIO_FAR)
    facts["place_entry_calls_after_restart"] = place_entry_calls(second) - sent_before
    if facts["place_entry_calls_after_restart"] != 1:
        raise dr._smoke_fail(
            env, recorder, STEP_ENTRY_ALLOWED, "the request was not placed after the clear"
        )
    record_reaction(
        env, recorder, STEP_ENTRY_ALLOWED, "a request is placed once the gate is clear again"
    )
    await cancel_resting_entry(second, recorder, placed)
    if not await account_clean(second, recorder):
        raise dr.SmokeHalt("account_clean")
