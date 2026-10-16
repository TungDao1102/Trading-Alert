"""The paper runtime's liveness stamp and the `--liveness` probe logic (plan 16-56 Task 4).

The separate paper heartbeat (owner decision 16-DEC-HUNG-RUNTIME, 16-55 Q2 = B, correction 2 of
16-DEC-FIXPLANS.md) must be driven by the 120 s feed-liveness and loop-alive signal, never by the
3900 s bar-age healthcheck. This module is that signal:

- The silence watchdog of the live loop (`src/paper/runtime.py`, `_LiveLoop._watch_feed`) writes,
  on every wake and from the event loop (never from the SDK thread), one small JSON file per
  container, `liveness-<container>.json`, in the directory of the pinned-state file
  (`logs/paper/`). It holds the container name (`socket.gethostname()`), the wall-clock time of
  this wake (`loop_alive_utc`) and the wall-clock time of the last message on the market
  connection (`last_frame_utc`; before the first frame, the time the watchdog started watching).
  A hung event loop stops refreshing it; a silent feed stops moving `last_frame_utc`.
- `python -m src.paper.runtime --liveness` passes only when no held marker of this container
  exists (`src/paper/held_marker.py`), the liveness file of this container exists and both of its
  times are within `health.feed_silence_timeout_seconds` of now. `deploy/heartbeat.sh --target
  paper` sends a success ping only when it passes.

The file never holds a value of the environment or of the configuration. Stdlib only; nothing here
is imported by the decision path.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from src.paper import held_marker

LIVENESS_SCHEMA = "paper-liveness/1"
LIVENESS_PREFIX = "liveness-"


@dataclass(frozen=True)
class LivenessStamp:
    """What the watchdog last wrote: who, when the loop was alive, when the feed last spoke."""

    container: str
    loop_alive_utc: datetime
    last_frame_utc: datetime


class LivenessUnreadable(Exception):
    """The liveness file exists but cannot be read or parsed (never counted as live)."""


def liveness_path(directory: Path, container: str | None = None) -> Path:
    """The liveness file of `container` (this container by default) in `directory`."""
    held = held_marker.marker_path(directory, container)
    return directory / (LIVENESS_PREFIX + held.name.removeprefix(held_marker.MARKER_PREFIX))


def _require_utc(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be a UTC datetime")


def write_liveness(
    directory: Path,
    *,
    loop_alive_utc: datetime,
    last_frame_utc: datetime,
    container: str | None = None,
) -> Path:
    """Write the stamp atomically (temporary file in the same directory, then replace).

    Raises:
        OSError: the file cannot be written (the caller logs it; the probe then fails).
    """
    _require_utc(loop_alive_utc, "loop_alive_utc")
    _require_utc(last_frame_utc, "last_frame_utc")
    name = container if container is not None else held_marker.container_name()
    path = liveness_path(directory, name)
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": LIVENESS_SCHEMA,
        "container": name,
        "loop_alive_utc": loop_alive_utc.isoformat(),
        "last_frame_utc": last_frame_utc.isoformat(),
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


def read_liveness(directory: Path, container: str | None = None) -> LivenessStamp | None:
    """The stamp of `container` (this container by default), or None when no file exists.

    Raises:
        LivenessUnreadable: the file exists but is not a readable stamp of this container.
    """
    name = container if container is not None else held_marker.container_name()
    path = liveness_path(directory, name)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw["schema"] != LIVENESS_SCHEMA:
            raise ValueError("unknown schema")
        stamp = LivenessStamp(
            container=str(raw["container"]),
            loop_alive_utc=datetime.fromisoformat(raw["loop_alive_utc"]),
            last_frame_utc=datetime.fromisoformat(raw["last_frame_utc"]),
        )
        _require_utc(stamp.loop_alive_utc, "loop_alive_utc")
        _require_utc(stamp.last_frame_utc, "last_frame_utc")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise LivenessUnreadable(type(exc).__name__) from None
    if stamp.container != name:
        raise LivenessUnreadable("the file names another container")
    return stamp


def liveness_problem(
    directory: Path,
    *,
    now_utc: datetime,
    bound_seconds: int,
    container: str | None = None,
) -> str | None:
    """None when this container is live; otherwise a one-line reason (names and ages only).

    Live means: no held marker of this container, a liveness file of this container, and both
    its loop-alive time and its last-frame time within `bound_seconds` of `now_utc`.
    """
    _require_utc(now_utc, "now_utc")
    bound = timedelta(seconds=bound_seconds)
    try:
        held = held_marker.read_own_marker(directory, container)
    except OSError as exc:
        return f"the held marker cannot be read ({type(exc).__name__})"
    if held is not None:
        return (
            f"the start was refused and this container is held ({held.refusal}, exit {held.code})"
        )
    try:
        stamp = read_liveness(directory, container)
    except LivenessUnreadable as exc:
        return f"the liveness file is unreadable ({exc})"
    if stamp is None:
        return "no liveness file: the live loop of this container has not stamped"
    loop_age = now_utc - stamp.loop_alive_utc
    if loop_age > bound:
        return (
            f"the event loop stamp is {int(loop_age.total_seconds())} s old: the loop is hung or "
            "stopped"
        )
    frame_age = now_utc - stamp.last_frame_utc
    if frame_age > bound:
        return f"no market message for {int(frame_age.total_seconds())} s: the feed is silent"
    return None


__all__ = [
    "LIVENESS_PREFIX",
    "LIVENESS_SCHEMA",
    "LivenessStamp",
    "LivenessUnreadable",
    "liveness_path",
    "liveness_problem",
    "read_liveness",
    "write_liveness",
]
