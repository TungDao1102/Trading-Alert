"""The explicit held marker of a refused paper start (plan 16-55, 16-DEC-RESTART-POLICY).

Under `--hold-on-refusal` a refused start (and SKIPPED) does not exit: it stays up, held and
non-operational, until it is stopped (owner decision 16-55 Q1 = A). The container probe alone
cannot see that hold: it reads the bar age from the store, and the store may hold a fresh bar of
an earlier run (a restart refused by an epoch mismatch or by the instance guard). So the hold
leaves this marker, and `--healthcheck` reports unhealthy while a marker of its own container
exists (correction 1 of 16-DEC-FIXPLANS.md), before it looks at any bar.

One small JSON file per container, `held-refusal-<container>.json`, in the directory of the
pinned-state file (`logs/paper/` on the logs volume). It holds the writing container's name
(`socket.gethostname()`, the container id under Docker), the process id, the exit code and the
refusal class name. It never holds a value of the environment or of the configuration.

- The hold writes it before it waits and removes it when the hold ends.
- A successful start of the same container removes a marker left by a killed hold, before
  RUNTIME_START. The probe never removes a marker.
- A marker that exists but cannot be read counts as held: a damaged marker must never make a
  held container look healthy.

Stdlib only; nothing here is imported by the decision path.
"""

from __future__ import annotations

import json
import os
import re
import socket
import tempfile
from dataclasses import dataclass
from pathlib import Path

MARKER_SCHEMA = "paper-held-refusal/1"
MARKER_PREFIX = "held-refusal-"
UNREADABLE = "UNREADABLE_MARKER"

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


@dataclass(frozen=True)
class HeldMarker:
    """What a held marker says: who holds, and why (a class name and a code, never a value)."""

    container: str
    pid: int
    code: int
    refusal: str


def container_name() -> str:
    """The name of this container: the host name, which Docker sets to the container id."""
    return socket.gethostname() or "unknown"


def marker_path(directory: Path, container: str | None = None) -> Path:
    """The marker file of `container` (this container by default) in `directory`."""
    name = container if container is not None else container_name()
    safe = _UNSAFE.sub("_", name) or "unknown"
    return directory / f"{MARKER_PREFIX}{safe}.json"


def write_marker(directory: Path, *, code: int, refusal: str, container: str | None = None) -> Path:
    """Write the marker atomically (temporary file in the same directory, then replace).

    Raises:
        OSError: the marker cannot be written; the caller must then not hold invisibly.
    """
    name = container if container is not None else container_name()
    path = marker_path(directory, name)
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": MARKER_SCHEMA,
        "container": name,
        "pid": os.getpid(),
        "code": int(code),
        "refusal": refusal,
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


def read_own_marker(directory: Path, container: str | None = None) -> HeldMarker | None:
    """The marker of `container` (this container by default), or None when it holds none.

    A file that exists but cannot be read or parsed is reported as held (refusal
    `UNREADABLE_MARKER`), never as absent.
    """
    name = container if container is not None else container_name()
    path = marker_path(directory, name)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        marker = HeldMarker(
            container=str(raw["container"]),
            pid=int(raw["pid"]),
            code=int(raw["code"]),
            refusal=str(raw["refusal"]),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return HeldMarker(container=name, pid=-1, code=-1, refusal=UNREADABLE)
    if marker.container != name:
        return None
    return marker


def remove_marker(directory: Path, container: str | None = None) -> None:
    """Remove the marker of `container` (this container by default); absent is a no-op."""
    marker_path(directory, container).unlink(missing_ok=True)


__all__ = [
    "MARKER_PREFIX",
    "MARKER_SCHEMA",
    "UNREADABLE",
    "HeldMarker",
    "container_name",
    "marker_path",
    "read_own_marker",
    "remove_marker",
    "write_marker",
]
