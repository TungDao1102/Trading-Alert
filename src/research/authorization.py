"""The research-run authorization guard (D-25, REV-04, REV-05, T-16-14).

A research run starts only when a user-written authorization binds BOTH the parameter-grid
hash and the dataset-manifest hash the runner is about to use, and names the simulator
semantics version the code carries (owner decision 16-60 Q4 = B: a file name or a date is a
human convention, a required key is machine-enforced). `require_authorized` raises
`RunNotAuthorized` (naming the cause) before any simulation, code-version read or file
write. What the authorization says and when it is written belong to the user (O-03).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from src.backtest.semantics import SIMULATOR_SEMANTICS_VERSION

from .manifest import DatasetManifest, ParameterGrid, grid_hash, manifest_hash


class RunNotAuthorized(Exception):  # noqa: N818 - the name is the plan's public contract
    """A research run was refused; `reason` names the cause."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class RunAuthorization:
    """What the user recorded: the exact grid and manifest hashes, when, a statement, and the
    simulator semantics version the authorization was written for."""

    grid_hash: str
    manifest_hash: str
    authorized_at_utc: datetime
    statement: str
    authorized_by: str
    simulator_semantics_version: str


_AUTHORIZATION_KEYS = frozenset(
    {
        "grid_sha256",
        "manifest_sha256",
        "authorized_at_utc",
        "statement",
        "authorized_by",
        "simulator_semantics_version",
    }
)


def _is_hex64(value: object) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


def _reject_number(text: str) -> object:
    raise ValueError("fractional numbers are not part of an authorization file")


def load_authorization(path: Path) -> RunAuthorization:
    """Read the user-committed authorization file (checkpoint O-03a, option a).

    The file is a JSON object with exactly `grid_sha256` and `manifest_sha256` (64 lowercase
    hex), `authorized_at_utc` (ISO-8601 with a UTC offset), `statement`, `authorized_by` and
    `simulator_semantics_version` (non-empty strings). A file with the earlier five keys is
    malformed: it can start no run. An absent or unreadable file is `RunNotAuthorized("missing")`;
    anything else wrong with it is `RunNotAuthorized("malformed")`.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise RunNotAuthorized("missing") from None
    try:
        payload = json.loads(text, parse_float=_reject_number)
    except ValueError:
        raise RunNotAuthorized("malformed") from None
    if not isinstance(payload, dict) or set(payload) != _AUTHORIZATION_KEYS:
        raise RunNotAuthorized("malformed")
    if not (_is_hex64(payload["grid_sha256"]) and _is_hex64(payload["manifest_sha256"])):
        raise RunNotAuthorized("malformed")
    for key in ("statement", "authorized_by", "simulator_semantics_version"):
        value = payload[key]
        if not isinstance(value, str) or not value.strip():
            raise RunNotAuthorized("malformed")
    stamp = payload["authorized_at_utc"]
    if not isinstance(stamp, str):
        raise RunNotAuthorized("malformed")
    try:
        authorized_at = datetime.fromisoformat(stamp)
    except ValueError:
        raise RunNotAuthorized("malformed") from None
    if authorized_at.tzinfo is None or authorized_at.utcoffset() != timedelta(0):
        raise RunNotAuthorized("malformed")
    return RunAuthorization(
        grid_hash=payload["grid_sha256"],
        manifest_hash=payload["manifest_sha256"],
        authorized_at_utc=authorized_at,
        statement=payload["statement"],
        authorized_by=payload["authorized_by"],
        simulator_semantics_version=payload["simulator_semantics_version"],
    )


def require_authorized(
    authorization: RunAuthorization | None,
    *,
    manifest: DatasetManifest,
    grid: ParameterGrid,
) -> None:
    """Raise `RunNotAuthorized` unless the authorization binds this grid, this manifest and the
    simulator semantics version of the code that is about to run."""
    if authorization is None:
        raise RunNotAuthorized("missing")
    if authorization.grid_hash != grid_hash(grid):
        raise RunNotAuthorized("grid_hash_mismatch")
    if authorization.manifest_hash != manifest_hash(manifest):
        raise RunNotAuthorized("manifest_hash_mismatch")
    if authorization.simulator_semantics_version != SIMULATOR_SEMANTICS_VERSION:
        raise RunNotAuthorized("simulator_semantics_version_mismatch")


__all__ = ["RunAuthorization", "RunNotAuthorized", "load_authorization", "require_authorized"]
