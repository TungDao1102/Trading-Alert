"""Configuration of the evidence remote (Phase 16, plan 16-47; decision O-01, option a).

Trial evidence is published to an S3-compatible bucket and prefix that are NOT the backup chain:
a distinct set of names, a distinct rclone remote and its own credentials, and no crypt layer
(`through_crypt_remote: no`). The pattern mirrors `src/ops/backup_remote.py`: operator values in
``EVIDENCE_S3_*`` environment variables are mapped to ``RCLONE_CONFIG_EVIDENCES3_*`` for the
child rclone process only, so a credential never appears in argv, and a change of provider
changes values only.

    EVIDENCE_S3_PROVIDER           AWS, Wasabi or Other (Other needs EVIDENCE_S3_ENDPOINT)
    EVIDENCE_S3_ENDPOINT           S3-compatible endpoint (empty for AWS and Wasabi)
    EVIDENCE_S3_REGION
    EVIDENCE_S3_BUCKET
    EVIDENCE_S3_PREFIX             required, never empty: where the epoch prefixes go
    EVIDENCE_S3_ACCESS_KEY_ID
    EVIDENCE_S3_SECRET_ACCESS_KEY

The names are not part of ``ALLOWED_ENV_NAMES`` (`src/paper/runtime_config.py`): the paper runtime
neither reads nor needs them, and none begins with ``BINANCE_``. Messages here name variables,
never values. Stdlib only, plus the provider rule shared with the backup mapping.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from src.ops.backup_remote import PROVIDERS_WITHOUT_ENDPOINT

EVIDENCE_REMOTE = "EVIDENCES3"

EVIDENCE_VARIABLES: tuple[str, ...] = (
    "EVIDENCE_S3_PROVIDER",
    "EVIDENCE_S3_ENDPOINT",
    "EVIDENCE_S3_REGION",
    "EVIDENCE_S3_BUCKET",
    "EVIDENCE_S3_PREFIX",
    "EVIDENCE_S3_ACCESS_KEY_ID",
    "EVIDENCE_S3_SECRET_ACCESS_KEY",
)

# Backup credentials the evidence remote must not reuse (it has its own credentials).
_BACKUP_CREDENTIAL_PAIRS: tuple[tuple[str, str], ...] = (
    ("EVIDENCE_S3_ACCESS_KEY_ID", "BACKUP_S3_ACCESS_KEY_ID"),
    ("EVIDENCE_S3_SECRET_ACCESS_KEY", "BACKUP_S3_SECRET_ACCESS_KEY"),
)

_SEGMENT = re.compile(r"[A-Za-z0-9._-]+")
_BUCKET = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{1,62}")
_CREDENTIAL_WORDS = re.compile(
    r"secret|passw|token|access[_-]?key|key[_-]?id|session|credential", re.IGNORECASE
)


class EvidenceConfigError(Exception):
    """The evidence configuration is incomplete or unusable. Names variables, never values."""


def _value(environ: Mapping[str, str], name: str) -> str:
    return environ.get(name, "").strip()


def _checked(environ: Mapping[str, str]) -> dict[str, str]:
    """The stripped values, after the completeness and safety checks."""
    provider = _value(environ, "EVIDENCE_S3_PROVIDER")
    required = [name for name in EVIDENCE_VARIABLES if name != "EVIDENCE_S3_ENDPOINT"]
    if provider.lower() not in PROVIDERS_WITHOUT_ENDPOINT:
        required.append("EVIDENCE_S3_ENDPOINT")
    missing = [name for name in required if not _value(environ, name)]
    if missing:
        raise EvidenceConfigError(
            "evidence configuration is incomplete; set: " + ", ".join(sorted(missing))
        )
    values = {name: _value(environ, name) for name in EVIDENCE_VARIABLES}

    unusable: list[str] = []
    bucket = values["EVIDENCE_S3_BUCKET"]
    if _BUCKET.fullmatch(bucket) is None or _CREDENTIAL_WORDS.search(bucket):
        unusable.append("EVIDENCE_S3_BUCKET")
    prefix = values["EVIDENCE_S3_PREFIX"]
    segments = prefix.split("/")
    if any(
        _SEGMENT.fullmatch(s) is None or s in {".", ".."} for s in segments
    ) or _CREDENTIAL_WORDS.search(prefix):
        unusable.append("EVIDENCE_S3_PREFIX")
    for evidence_name, backup_name in _BACKUP_CREDENTIAL_PAIRS:
        shared = _value(environ, backup_name)
        if shared and shared == values[evidence_name]:
            unusable.append(evidence_name)
    if unusable:
        raise EvidenceConfigError(
            "evidence configuration is unusable (a safe bucket and prefix, and credentials "
            "of their own, are required); check: " + ", ".join(sorted(unusable))
        )
    return values


def rclone_env(environ: Mapping[str, str]) -> dict[str, str]:
    """Map ``EVIDENCE_S3_*`` to ``RCLONE_CONFIG_EVIDENCES3_*`` (one plain S3 remote, no crypt)."""
    values = _checked(environ)
    s3 = f"RCLONE_CONFIG_{EVIDENCE_REMOTE}_"
    return {
        f"{s3}TYPE": "s3",
        f"{s3}PROVIDER": values["EVIDENCE_S3_PROVIDER"],
        f"{s3}ENDPOINT": values["EVIDENCE_S3_ENDPOINT"],
        f"{s3}REGION": values["EVIDENCE_S3_REGION"],
        # The bucket is created out-of-band by the operator; see the same note in
        # src/ops/backup_remote.py (least-privilege users get 404 on HeadBucket).
        f"{s3}NO_CHECK_BUCKET": "true",
        f"{s3}ACCESS_KEY_ID": values["EVIDENCE_S3_ACCESS_KEY_ID"],
        f"{s3}SECRET_ACCESS_KEY": values["EVIDENCE_S3_SECRET_ACCESS_KEY"],
    }


def destination(environ: Mapping[str, str]) -> str:
    """``EVIDENCES3:<bucket>/<prefix>``: the base under which ``<epoch_id>/<file>`` is stored."""
    values = _checked(environ)
    return f"{EVIDENCE_REMOTE}:{values['EVIDENCE_S3_BUCKET']}/{values['EVIDENCE_S3_PREFIX']}"
