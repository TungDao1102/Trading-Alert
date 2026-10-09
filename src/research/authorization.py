"""The research-run authorization guard (D-25, REV-04, REV-05, T-16-14).

A research run starts only when a user-written authorization binds BOTH the parameter-grid
hash and the dataset-manifest hash the runner is about to use. `require_authorized` raises
`RunNotAuthorized` (naming the cause) before any simulation, code-version read or file
write. What the authorization says and when it is written belong to the user (O-03).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .manifest import DatasetManifest, ParameterGrid, grid_hash, manifest_hash


class RunNotAuthorized(Exception):  # noqa: N818 - the name is the plan's public contract
    """A research run was refused; `reason` names the cause."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class RunAuthorization:
    """What the user recorded: the exact grid and manifest hashes, when, and a statement."""

    grid_hash: str
    manifest_hash: str
    authorized_at_utc: datetime
    statement: str


def require_authorized(
    authorization: RunAuthorization | None,
    *,
    manifest: DatasetManifest,
    grid: ParameterGrid,
) -> None:
    """Raise `RunNotAuthorized` unless the authorization binds this grid and this manifest."""
    if authorization is None:
        raise RunNotAuthorized("missing")
    if authorization.grid_hash != grid_hash(grid):
        raise RunNotAuthorized("grid_hash_mismatch")
    if authorization.manifest_hash != manifest_hash(manifest):
        raise RunNotAuthorized("manifest_hash_mismatch")


__all__ = ["RunAuthorization", "RunNotAuthorized", "require_authorized"]
