"""The file store of the REST gate state (plan 20-07, T-D; owner decision O-C = option a1).

`FileGateStateStore` keeps the two persisted deadlines of `RestRateLimitGate` in one small JSON
file (schema_version 1: canonical, sorted keys, UTC ISO text). It implements the
`GateStateStore` Protocol of `src.adapters.binance_ratelimit_gate`, so the gate itself does no
I/O.

A first installation is proven ONLY by `initialize(now_utc=..., operator_id=...)`, which writes a
record carrying `initialized_at_utc`; a missing file alone never proves a fresh install, and a
file that does not parse is corruption. Both read as loss of initialized state to the gate.

Writes are atomic: a temporary file in the same directory, fsync, then `replace_with_retry`.
The store reads no wall clock: the injected `clock` only names a corrupt file that is set aside
(the file is kept, never deleted).
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.adapters.binance_ratelimit_gate import (
    GATE_STATE_SCHEMA_VERSION,
    GateStateCorrupt,
    GateStateRecord,
)
from src.data.store import replace_with_retry

_KEYS = frozenset(
    {
        "ban_until_utc",
        "initialized_at_utc",
        "initialized_by",
        "pause_until_utc",
        "recorded_at_utc",
        "schema_version",
    }
)


class GateStateExists(Exception):  # noqa: N818 - a refusal of the bootstrap, not an error
    """`initialize()` was refused because a state file already exists (it is left untouched)."""


@dataclass(frozen=True, slots=True)
class GateStateInspection:
    """The result of a read-only look at the state file (`FileGateStateStore.inspect`).

    `exists` is False for a missing file; `corrupt` is True for a file that does not parse;
    `record` is the parsed record of a valid file, else None.
    """

    exists: bool
    corrupt: bool
    record: GateStateRecord | None


def _format_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_time(value: object, *, required: bool) -> datetime | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise GateStateCorrupt
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise GateStateCorrupt from None
    if parsed.utcoffset() is None:
        raise GateStateCorrupt
    return parsed.astimezone(UTC)


def encode_record(record: GateStateRecord) -> bytes:
    """The canonical bytes of `record` (sorted keys, UTC ISO text, trailing newline)."""
    payload: dict[str, Any] = {
        "ban_until_utc": _format_time(record.ban_until_utc),
        "initialized_at_utc": _format_time(record.initialized_at_utc),
        "initialized_by": record.initialized_by,
        "pause_until_utc": _format_time(record.pause_until_utc),
        "recorded_at_utc": _format_time(record.recorded_at_utc),
        "schema_version": record.schema_version,
    }
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def decode_record(data: bytes) -> GateStateRecord:
    """Parse strictly; any deviation raises `GateStateCorrupt` (no message, no content)."""
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise GateStateCorrupt from None
    if not isinstance(payload, dict) or set(payload) != _KEYS:
        raise GateStateCorrupt
    version = payload["schema_version"]
    if isinstance(version, bool) or version != GATE_STATE_SCHEMA_VERSION:
        raise GateStateCorrupt
    initialized_by = payload["initialized_by"]
    if not isinstance(initialized_by, str) or not initialized_by.strip():
        raise GateStateCorrupt
    recorded_at = _parse_time(payload["recorded_at_utc"], required=True)
    initialized_at = _parse_time(payload["initialized_at_utc"], required=True)
    if recorded_at is None or initialized_at is None:
        raise GateStateCorrupt
    return GateStateRecord(
        ban_until_utc=_parse_time(payload["ban_until_utc"], required=False),
        pause_until_utc=_parse_time(payload["pause_until_utc"], required=False),
        recorded_at_utc=recorded_at,
        initialized_at_utc=initialized_at,
        initialized_by=initialized_by,
    )


class FileGateStateStore:
    """`GateStateStore` over one JSON file; see the module docstring."""

    def __init__(self, path: Path | str, *, clock: Callable[[], datetime]) -> None:
        if not callable(clock):
            raise TypeError("clock must be a callable returning a timezone-aware datetime")
        self._path = Path(path)
        self._clock = clock

    @property
    def path(self) -> Path:
        return self._path

    def _aside_path(self, kind: str) -> Path:
        stamp = self._clock().astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        base = self._path.with_name(f"{self._path.name}.{kind}-{stamp}")
        candidate = base
        counter = 0
        while candidate.exists():
            counter += 1
            candidate = base.with_name(f"{base.name}-{counter}")
        return candidate

    def _write_atomic(self, data: bytes) -> None:
        tmp = self._path.with_name(f".{self._path.name}.{os.getpid()}.tmp")
        try:
            with open(tmp, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            replace_with_retry(tmp, self._path)
        finally:
            tmp.unlink(missing_ok=True)

    def load(self) -> GateStateRecord | None:
        """The record, None for a missing file; a file that does not parse is set aside.

        An unparsable file is renamed to a sibling ending `.corrupt-<UTC time>` (kept, never
        deleted) and `GateStateCorrupt` is raised. An I/O error (for example a permission
        error) propagates and leaves the file where it is.
        """
        try:
            data = self._path.read_bytes()
        except FileNotFoundError:
            return None
        try:
            return decode_record(data)
        except GateStateCorrupt:
            try:
                replace_with_retry(self._path, self._aside_path("corrupt"))
            except OSError:
                # Could not move it: the corruption is still reported, and it is detected
                # again at the next start. The file is never deleted.
                pass
            raise

    def inspect(self) -> GateStateInspection:
        """Read-only look at the file: never renames, moves or writes anything."""
        try:
            data = self._path.read_bytes()
        except FileNotFoundError:
            return GateStateInspection(exists=False, corrupt=False, record=None)
        try:
            return GateStateInspection(exists=True, corrupt=False, record=decode_record(data))
        except GateStateCorrupt:
            return GateStateInspection(exists=True, corrupt=True, record=None)

    def save(self, record: GateStateRecord) -> None:
        """Atomically replace the file with `record`; raises on a failure to persist."""
        self._write_atomic(encode_record(record))

    def initialize(self, *, now_utc: datetime, operator_id: str) -> GateStateRecord:
        """The explicit first-install bootstrap: write an initialized record, no deadline.

        Refused (`GateStateExists`, file untouched) while any state file exists, a corrupt one
        included. Run once before the first start of the process.
        """
        record = _fresh_record(now_utc, operator_id)
        if self._path.exists():
            raise GateStateExists
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._write_atomic(encode_record(record))
        return record

    def reinitialize(
        self, *, now_utc: datetime, operator_id: str, aside_kind: str
    ) -> GateStateRecord:
        """The operator-authorised overwrite used only by `clear` (`rest_gate_cli`).

        Writes a fresh initialized record with no deadline. An existing file is first copied to
        a sibling ending `.<aside_kind>-<UTC time>` (kept, never deleted), then replaced
        atomically. On any failure the old file is untouched, no copy is left behind and the
        error propagates. `initialize()` stays refused while a state file exists.
        """
        record = _fresh_record(now_utc, operator_id)
        if not aside_kind.isalpha():
            raise ValueError("aside_kind must be alphabetic")
        aside: Path | None = None
        try:
            if self._path.exists():
                aside = self._aside_path(aside_kind)
                shutil.copyfile(self._path, aside)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._write_atomic(encode_record(record))
        except BaseException:
            if aside is not None:
                aside.unlink(missing_ok=True)
            raise
        return record


def _fresh_record(now_utc: datetime, operator_id: str) -> GateStateRecord:
    if not isinstance(now_utc, datetime) or now_utc.utcoffset() is None:
        raise ValueError("now_utc must be a timezone-aware datetime")
    if not isinstance(operator_id, str) or not operator_id.strip():
        raise ValueError("operator_id must be a non-empty string")
    return GateStateRecord(
        ban_until_utc=None,
        pause_until_utc=None,
        recorded_at_utc=now_utc,
        initialized_at_utc=now_utc,
        initialized_by=operator_id.strip(),
    )


__all__ = [
    "FileGateStateStore",
    "GateStateExists",
    "GateStateInspection",
    "decode_record",
    "encode_record",
]
