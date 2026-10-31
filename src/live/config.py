"""Admission configuration of the live process (plan 24-11; D-02, D-03, D-12, OPS-02, OPS-04).

`parse_live_environment` is the one place that decides whether the live process may start. It
refuses, in this order, and always by NAME (a variable or a limit key), never by value:

1. the mode (D-02): `LIVE_RUNTIME_MODE` must be exactly `DEMO` or `LIVE`, never inferred from a
   URL; `LIVE` refuses while live placement is disabled (`LIVE_ORDERS_DISABLED`, the default of
   `LiveEnablementController`);
2. the Binance credentials: only the names of the chosen mode are read, and the presence of any
   name of the other mode (or its `_FILE` form) refuses the whole start (T-24-27);
3. the Telegram variables (24-01 Q6): the live process has its own bot, so the SHADOW bot
   variable must be absent and the live-only names must be present and well formed;
4. the execution limits (D-12): the limits file must load and no required key may be
   `NOT_CONFIGURED`.

Loaded secrets are registered with `src/ops/redaction.py` (OPS-02). This module reads no clock
and opens no network or database client; the CLI edge is `src/live/runtime.py`.

The live liveness stamp (a small JSON file the scheduler's liveness task writes, plan 24-27, and
the `--liveness` / `--healthcheck` verbs read) lives here too, so both sides share one schema.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum
from pathlib import Path
from typing import Any

from src.adapters.binance_client import (
    ApiCredentials,
    CredentialError,
    Environment,
    credential_spec_for,
    load_api_credentials,
)
from src.execution.enablement import LiveEnablementController
from src.execution.execution_limits import (
    ExecutionLimits,
    ExecutionLimitsInvalid,
    load_execution_limits,
)
from src.ops.redaction import register_runtime_secret
from src.paper import held_marker

MODE_VARIABLE = "LIVE_RUNTIME_MODE"
# Telegram identity of the live process (24-01 Q6): its own bot, the same owner chat and users.
TELEGRAM_TOKEN_VARIABLE = "TELEGRAM_LIVE_BOT_TOKEN"
TELEGRAM_CHAT_VARIABLE = "TELEGRAM_LIVE_AUTHORIZED_CHAT_ID"
TELEGRAM_USER_IDS_VARIABLE = "TELEGRAM_AUTHORIZED_USER_IDS"
# The SHADOW bot's names: one getUpdates consumer per bot token (BOT_TOKEN_RULE), so their
# presence in the live environment refuses the start.
SHADOW_TELEGRAM_VARIABLES: tuple[str, ...] = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN_FILE")

ACCEPTED_MODES: Mapping[str, Environment] = {
    Environment.DEMO.value: Environment.DEMO,
    Environment.LIVE.value: Environment.LIVE,
}
UNRESOLVED_MODE = "UNRESOLVED"

DEFAULT_STATE_DIR = Path("logs/live")
GATE_STATE_FILE = "rest_gate_state.json"
SPILL_DIRECTORY = "spill"
DEFAULT_LIMITS_RELATIVE = Path("config") / "execution" / "execution-limits-v1.toml"

LIVE_LIVENESS_SCHEMA = "live-liveness/1"
LIVE_LIVENESS_PREFIX = "live-liveness-"


class LiveExitCode(IntEnum):
    """Process exit statuses of `python -m src.live.runtime` (final table: the 24-11 SUMMARY)."""

    OK = 0
    USAGE = 2
    CREDENTIAL_REFUSED = 3
    LIMITS_NOT_CONFIGURED = 4
    MODE_REFUSED = 5
    STARTUP_FAILED = 7


class LiveRefusal(Exception):  # noqa: N818 - a refusal of the admission, not an error
    """A refused start: the exit code, a reason that names variables or keys only, the mode."""

    def __init__(self, code: LiveExitCode, reason: str, mode_label: str = UNRESOLVED_MODE) -> None:
        self.code = code
        self.reason = reason
        self.mode_label = mode_label
        super().__init__(f"{code.name} (mode {mode_label}): {reason}")


@dataclass(frozen=True, kw_only=True)
class LiveConfig:
    """What an admitted start carries. Secrets are hidden from `repr`."""

    mode: Environment
    credentials: ApiCredentials = field(repr=False)
    telegram_bot_token: str = field(repr=False)
    authorized_chat_id: int = field(repr=False)
    authorized_user_ids: frozenset[int] = field(repr=False)
    limits: ExecutionLimits
    telegram_token_variable: str = TELEGRAM_TOKEN_VARIABLE
    telegram_chat_variable: str = TELEGRAM_CHAT_VARIABLE
    telegram_user_ids_variable: str = TELEGRAM_USER_IDS_VARIABLE
    state_dir: Path
    gate_state_path: Path
    spill_dir: Path
    held_marker_dir: Path
    liveness_dir: Path


class _NoJournal:
    """A journal that is never written: the controller below is only asked for its default."""

    def record(self, event: Any) -> None:
        raise AssertionError("the default-state probe never writes a journal record")


def live_orders_disabled_by_default() -> bool:
    """True while live placement is disabled: the default of the enablement controller."""
    return LiveEnablementController(journal=_NoJournal()).is_disabled


def default_limits_path(repo_root: Path) -> Path:
    """The shipped execution-limits file of a repository (or image) root."""
    return repo_root / DEFAULT_LIMITS_RELATIVE


def resolve_mode(environ: Mapping[str, str]) -> Environment:
    """The explicit mode, exactly `DEMO` or `LIVE` (D-02). The value is never echoed.

    Raises:
        LiveRefusal: MODE_REFUSED for a missing, non-exact or unsupported value (TESTNET too).
    """
    raw = environ.get(MODE_VARIABLE)
    if raw is None:
        raise LiveRefusal(LiveExitCode.MODE_REFUSED, f"{MODE_VARIABLE} is missing")
    mode = ACCEPTED_MODES.get(raw)
    if mode is None:
        raise LiveRefusal(
            LiveExitCode.MODE_REFUSED, f"{MODE_VARIABLE} must be exactly DEMO or LIVE"
        )
    return mode


def _other_mode(mode: Environment) -> Environment:
    return Environment.LIVE if mode is Environment.DEMO else Environment.DEMO


def _positive_int(text: str) -> int | None:
    item = text.strip(" \t\r\n")
    if not item or not item.isascii() or not item.isdigit() or item.startswith("0"):
        return None
    return int(item)


def parse_user_ids(text: str) -> frozenset[int]:
    """The Telegram user allow-list: comma-separated positive integers, no blanks, no duplicates.

    The same rule as the paper process applies to the same variable (Phase 23, D-02); it is kept
    here because the live process must not import the paper runtime modules (D-01). The
    `ValueError` names the variable only, never the input.
    """
    members: set[int] = set()
    for raw in text.split(","):
        user_id = _positive_int(raw)
        if user_id is None or user_id in members:
            raise ValueError(
                f"{TELEGRAM_USER_IDS_VARIABLE} must be comma-separated positive integers"
            )
        members.add(user_id)
    return frozenset(members)


def parse_live_environment(
    environ: Mapping[str, str],
    *,
    repo_root: Path,
    limits_path: Path | None = None,
    state_dir: Path | None = None,
    live_orders_disabled: bool | None = None,
) -> LiveConfig:
    """Admit the live process or raise `LiveRefusal` (mode, credentials, Telegram, limits).

    `live_orders_disabled` is a test seam; production leaves it None and reads the default of
    the enablement controller.

    Raises:
        LiveRefusal: with the exit code and a reason naming variables or keys, never values.
    """
    mode = resolve_mode(environ)
    label = mode.value

    def refuse(code: LiveExitCode, reason: str) -> LiveRefusal:
        return LiveRefusal(code, reason, label)

    disabled = (
        live_orders_disabled_by_default() if live_orders_disabled is None else live_orders_disabled
    )
    if mode is Environment.LIVE and disabled:
        raise refuse(
            LiveExitCode.MODE_REFUSED,
            "LIVE mode refused while live placement is disabled (LIVE_ORDERS_DISABLED)",
        )

    try:
        credentials = load_api_credentials(
            environ,
            spec=credential_spec_for(mode),
            repo_root=repo_root,
            refuse_if_present=(credential_spec_for(_other_mode(mode)),),
        )
    except CredentialError as exc:
        raise refuse(LiveExitCode.CREDENTIAL_REFUSED, str(exc)) from None

    present = [name for name in SHADOW_TELEGRAM_VARIABLES if name in environ]
    if present:
        raise refuse(
            LiveExitCode.CREDENTIAL_REFUSED,
            "the SHADOW bot variable is present, the live process has its own bot: "
            + ", ".join(present),
        )
    token = (environ.get(TELEGRAM_TOKEN_VARIABLE) or "").strip()
    chat_text = environ.get(TELEGRAM_CHAT_VARIABLE)
    users_text = environ.get(TELEGRAM_USER_IDS_VARIABLE)
    missing = [
        name
        for name, value in (
            (TELEGRAM_TOKEN_VARIABLE, token),
            (TELEGRAM_CHAT_VARIABLE, (chat_text or "").strip()),
            (TELEGRAM_USER_IDS_VARIABLE, (users_text or "").strip()),
        )
        if not value
    ]
    if missing:
        raise refuse(
            LiveExitCode.CREDENTIAL_REFUSED,
            "telegram variable missing or blank: " + ", ".join(missing),
        )
    assert chat_text is not None and users_text is not None
    chat_id = _positive_int(chat_text)
    if chat_id is None:
        raise refuse(
            LiveExitCode.CREDENTIAL_REFUSED,
            f"{TELEGRAM_CHAT_VARIABLE} must be a positive integer (a private chat)",
        )
    try:
        user_ids = parse_user_ids(users_text)
    except ValueError as exc:
        raise refuse(LiveExitCode.CREDENTIAL_REFUSED, str(exc)) from None
    register_runtime_secret(token)

    path = limits_path if limits_path is not None else default_limits_path(repo_root)
    try:
        limits = load_execution_limits(path)
    except ExecutionLimitsInvalid as exc:
        raise refuse(LiveExitCode.LIMITS_NOT_CONFIGURED, str(exc)) from None
    unset = limits.unset_keys()
    if unset:
        raise refuse(
            LiveExitCode.LIMITS_NOT_CONFIGURED,
            "execution limits not configured: " + ", ".join(unset),
        )

    directory = state_dir if state_dir is not None else DEFAULT_STATE_DIR
    return LiveConfig(
        mode=mode,
        credentials=credentials,
        telegram_bot_token=token,
        authorized_chat_id=chat_id,
        authorized_user_ids=user_ids,
        limits=limits,
        state_dir=directory,
        gate_state_path=directory / GATE_STATE_FILE,
        spill_dir=directory / SPILL_DIRECTORY,
        held_marker_dir=directory,
        liveness_dir=directory,
    )


# --------------------------------------------------------------------------- #
# The live liveness stamp (written by the scheduler's liveness task, read by the probes).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LiveLivenessStamp:
    """Who stamped, in which mode, when the loop was last alive, and the latest task results."""

    container: str
    mode: str
    loop_alive_utc: datetime
    # Task name -> its latest result code (for example "PASS"); never a value of the environment.
    tasks: Mapping[str, str]


class LiveLivenessUnreadable(Exception):  # noqa: N818 - a state of the file, not an error
    """The stamp exists but cannot be read or parsed (never counted as live)."""


def _require_utc(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be a UTC datetime")


def live_liveness_path(directory: Path, container: str | None = None) -> Path:
    """The stamp file of `container` (this container by default) in `directory`."""
    held = held_marker.marker_path(directory, container)
    return directory / (LIVE_LIVENESS_PREFIX + held.name.removeprefix(held_marker.MARKER_PREFIX))


def write_live_liveness(
    directory: Path,
    *,
    mode: str,
    loop_alive_utc: datetime,
    tasks: Mapping[str, str],
    container: str | None = None,
) -> Path:
    """Write the stamp atomically (temporary file in the same directory, then replace).

    Raises:
        OSError: the file cannot be written (the caller logs it; the probe then fails).
    """
    _require_utc(loop_alive_utc, "loop_alive_utc")
    name = container if container is not None else held_marker.container_name()
    path = live_liveness_path(directory, name)
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": LIVE_LIVENESS_SCHEMA,
        "container": name,
        "mode": mode,
        "loop_alive_utc": loop_alive_utc.isoformat(),
        "tasks": {str(key): str(value) for key, value in sorted(tasks.items())},
    }
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True))
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return path


def remove_live_liveness(directory: Path, container: str | None = None) -> None:
    """Remove the stamp of `container` (this container by default); an absent file is fine."""
    live_liveness_path(directory, container).unlink(missing_ok=True)


def read_live_liveness(directory: Path, container: str | None = None) -> LiveLivenessStamp | None:
    """The stamp of `container` (this container by default), or None when no file exists.

    Raises:
        LiveLivenessUnreadable: the file exists but is not a readable stamp of this container.
    """
    name = container if container is not None else held_marker.container_name()
    path = live_liveness_path(directory, name)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw["schema"] != LIVE_LIVENESS_SCHEMA:
            raise LiveLivenessUnreadable(f"not a stamp of schema {LIVE_LIVENESS_SCHEMA}")
        tasks_raw = raw["tasks"]
        if not isinstance(tasks_raw, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in tasks_raw.items()
        ):
            raise LiveLivenessUnreadable("tasks is not a text mapping")
        stamp = LiveLivenessStamp(
            container=str(raw["container"]),
            mode=str(raw["mode"]),
            loop_alive_utc=datetime.fromisoformat(raw["loop_alive_utc"]),
            tasks=dict(tasks_raw),
        )
        _require_utc(stamp.loop_alive_utc, "loop_alive_utc")
    except LiveLivenessUnreadable:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise LiveLivenessUnreadable(type(exc).__name__) from None
    if stamp.container != name:
        raise LiveLivenessUnreadable("the file names another container")
    return stamp


def live_liveness_problem(
    directory: Path,
    *,
    now_utc: datetime,
    bound_ms: int,
    container: str | None = None,
) -> str | None:
    """None when this container is live; otherwise a one-line reason (names and ages only).

    Live means: no held marker of this container and a readable stamp of this container whose
    loop-alive time is not in the future and not older than `bound_ms`.
    """
    _require_utc(now_utc, "now_utc")
    try:
        held = held_marker.read_own_marker(directory, container)
    except OSError as exc:
        return f"the held marker cannot be read ({type(exc).__name__})"
    if held is not None:
        return (
            f"the start was refused and this container is held ({held.refusal}, exit {held.code})"
        )
    try:
        stamp = read_live_liveness(directory, container)
    except LiveLivenessUnreadable as exc:
        return f"the liveness stamp is unreadable ({exc})"
    if stamp is None:
        return "no liveness stamp: the live loop of this container has not stamped"
    age_ms = (now_utc - stamp.loop_alive_utc) // timedelta(milliseconds=1)
    if age_ms < 0:
        return "the liveness stamp is dated in the future"
    if age_ms > bound_ms:
        return f"the liveness stamp is {age_ms} ms old (bound {bound_ms} ms): the loop is hung"
    return None


__all__ = [
    "ACCEPTED_MODES",
    "DEFAULT_STATE_DIR",
    "LIVE_LIVENESS_PREFIX",
    "LIVE_LIVENESS_SCHEMA",
    "MODE_VARIABLE",
    "SHADOW_TELEGRAM_VARIABLES",
    "TELEGRAM_CHAT_VARIABLE",
    "TELEGRAM_TOKEN_VARIABLE",
    "TELEGRAM_USER_IDS_VARIABLE",
    "LiveConfig",
    "LiveExitCode",
    "LiveLivenessStamp",
    "LiveLivenessUnreadable",
    "LiveRefusal",
    "default_limits_path",
    "live_liveness_path",
    "live_liveness_problem",
    "live_orders_disabled_by_default",
    "parse_live_environment",
    "parse_user_ids",
    "parse_user_ids",
    "read_live_liveness",
    "remove_live_liveness",
    "resolve_mode",
    "write_live_liveness",
]
