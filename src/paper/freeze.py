"""Paper freeze monitor — pinned epoch + diff-proof per-epoch evidence (Phase 7, plan 07-04).

Per D-04: the soak pins its registry version at start (parameterSetId +
parameterSetHash, cost keys included via the 07.1 binding gate). Any
registry diff against the pinned set halts the stream's evidence claim:
the change is logged with a new stream epoch, and evidence windows are
per-epoch. The PAPER-03 acceptance artifact is the diff log showing the
pinned hash untouched for the whole window.

Public surface (the only symbols downstream code uses):

  - `StreamEpoch` — frozen dataclass carrying the pinned
    (parameterSetId, parameterSetHash, opened_at_utc) tuple plus the
    `evidence_claim_open` flag. `epoch_id` is the content hash of the
    tuple, so two streams opened at different times against the same
    registry get distinct epoch_ids.
  - `DiffLogEntry` — frozen dataclass carrying the JSONL line written
    to the diff log on every tick (checked_at_utc, epoch_id,
    pinned_hash, current_hash, outcome).
  - `FreezeCheckOutcome` — frozen dataclass returning both the
    pinned_epoch (original) and the current_epoch (after the check);
    on a rollover, `halted_epoch` is a frozen copy of the pinned
    epoch with `evidence_claim_open=False` and `halted_reason` is
    "REGISTRY_DIFF". The pinned_epoch itself is never mutated
    (frozen dataclass), so its parameter_set_hash string is preserved
    (D-04).
  - `pin_stream_epoch(...)` — load the registry ParameterSet, run the
    07.1 binding gate (CostModelBindingMismatch on inequality, bare
    KeyError on absent slice keys), and return the StreamEpoch. It is
    called by `run_paper_tick` (src/paper/loop.py) at the start of every
    paper tick, before any candle is parsed (G-15-11, D-16, D-27): a
    per-call gate. The runtime (plan 16-22) adds a once-per-process start
    gate and persists the pinned epoch once; this module persists nothing
    on a pin.
  - `resolve_registry_root(...)` — the registry root a call judges: an
    explicit override, else `src.domain.registry.REGISTRY_ROOT` read at
    call time (never bound at import, review IN-05).
  - `load_parameter_set_at_root(...)` — load a ParameterSet from an
    explicit registry root; `run_paper_tick` uses it so the loop and the
    gate read the same root.
  - `check_registry_unchanged(...)` — re-read the registry, compare
    canonical hashes, append one JSONL entry to the diff log. Returns
    a FreezeCheckOutcome: on a clean tick current_epoch == pinned_epoch
    and halted_epoch is None; on a rollover current_epoch is a new
    StreamEpoch and halted_epoch is the frozen halted copy.
  - `run_check_cli(...)` — the CLI entry point invoked by the
    scheduled GitHub Actions workflow. Loads the pinned state from
    JSON, calls `check_registry_unchanged`, writes the diff-log
    entry, and writes the new pinned state on rollover. Exits 0 on
    success, non-zero on missing state.

`PaperAllowlistEntry` and `PAPER_START_ALLOWLIST` are module-internal policy
data read by `pin_stream_epoch` and, through the accessors `allowlist_entries()`
and `find_allowlist_entry()`, by the freeze CLI and the runtime (plan 16-22).
The allowlist is empty by the user's decision at checkpoint 15-17-01 (Option B),
is consulted only for sets without rationale tables, and is guarded by
tests/test_paper_start_gate.py.

Plan 16-09 adds `--from-allowlist` to the CLI (`run_allowlist_check_cli`): the
ids come from the allowlist, never from the caller. An empty allowlist appends
one `FreezeSkippedEntry` line (outcome "SKIPPED", reason "allowlist empty") and
exits 0; it is never a clean tick and never falls back to a set. One entry is
checked exactly like the explicit-id call, plus the rule that the pinned hash
equals the entry's hash. Every line may carry `run_metadata` (run id, attempt,
event name, cron string, commit) read from five named environment variables, so
a reconciler can tell scheduled ticks from manual runs.

The module owns the freeze-monitor slice: registry reads go through
`src/domain/registry.py`, cost-key binding through `src/backtest/`
(mirroring the 07.1 binding gate), canonical digests through
`src/domain/canonical.py`. No WS/Telegram/ORM/frame types enter this
module; only these named sibling surfaces do.

FLAGGED ASSUMPTION (PAPER-03 unclassified): the freeze-monitor tick
cadence (hourly or daily) and the minimum-evidence signal-frequency
gate are researcher-set values recorded in the soak log, not code
defaults. The hourly cron in `.github/workflows/paper_freeze_check.yml`
is the suggested default; the soak-host scheduled process is the
documented operator alternative.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import structlog

from src.backtest.binding import assert_cost_model_binds_registry
from src.backtest.costs import CostModel, build_cost_model, cost_slice
from src.domain import registry as _registry
from src.domain.canonical import sha256_hex
from src.domain.rationale import (
    UnrationalizedParameterSet,
    check_rationale_text,
    placeholder_keys_text,
)
from src.domain.registry import (
    ParameterSet,
    _check_registry_segment,
    _parse_and_validate,
)

log = structlog.get_logger()

# --------------------------------------------------------------------------- #
# StreamEpoch — pinned parameter set epoch.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class StreamEpoch:
    """A pinned parameter set epoch (D-04).

    Carries the canonical identity tuple for the running stream:
    `strategy_id`, `parameter_set_id`, `parameter_set_hash`,
    `opened_at_utc`. The `epoch_id` is the content-hash of the tuple
    — two streams opened at different times against the same registry
    get distinct epoch_ids, so per-stream journal rows never collide.

    `evidence_claim_open` is True while this epoch is the active one.
    On a rollover, a frozen copy with `evidence_claim_open=False` is
    returned in `FreezeCheckOutcome.halted_epoch` for journaling; the
    original pinned_epoch is never mutated.
    """

    epoch_id: str
    strategy_id: str
    parameter_set_id: str
    parameter_set_hash: str
    opened_at_utc: datetime
    evidence_claim_open: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.epoch_id, str) or len(self.epoch_id) != 64:
            raise ValueError(
                "epoch_id must be a 64-hex SHA256 string, "
                f"got len={len(self.epoch_id) if isinstance(self.epoch_id, str) else '?'}"
            )
        if not all(c in "0123456789abcdef" for c in self.epoch_id):
            raise ValueError("epoch_id must be lowercase hex")
        if not isinstance(self.strategy_id, str) or self.strategy_id == "":
            raise ValueError("strategy_id must be a non-empty string")
        if not isinstance(self.parameter_set_id, str) or self.parameter_set_id == "":
            raise ValueError("parameter_set_id must be a non-empty string")
        if not isinstance(self.parameter_set_hash, str) or len(self.parameter_set_hash) != 64:
            raise ValueError(
                "parameter_set_hash must be a 64-hex SHA256 string, "
                f"got len={len(self.parameter_set_hash)}"
            )
        if not all(c in "0123456789abcdef" for c in self.parameter_set_hash):
            raise ValueError("parameter_set_hash must be lowercase hex")
        if self.opened_at_utc.tzinfo is None:
            raise ValueError("opened_at_utc must be UTC-aware, got naive datetime")


# --------------------------------------------------------------------------- #
# DiffLogEntry — one JSONL line written per tick.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DiffLogEntry:
    """One JSONL line written by check_registry_unchanged.

    Per D-04: the PAPER-03 acceptance artifact is the diff log. Every
    tick appends exactly one line carrying the pinned epoch_id, the
    pinned hash, the current hash, and the outcome ("clean" or
    "REGISTRY_DIFF").
    """

    checked_at_utc: datetime
    epoch_id: str
    pinned_hash: str
    current_hash: str
    outcome: str  # "clean" or "REGISTRY_DIFF"
    run_metadata: Mapping[str, str] | None = None
    """Run identity copied from the runner environment (plan 16-09); rendered only when set."""

    def __post_init__(self) -> None:
        if self.checked_at_utc.tzinfo is None:
            raise ValueError("checked_at_utc must be UTC-aware")
        if self.outcome not in ("clean", "REGISTRY_DIFF"):
            raise ValueError(f"outcome must be 'clean' or 'REGISTRY_DIFF', got {self.outcome!r}")
        _check_run_metadata(self.run_metadata)

    def to_jsonl(self) -> str:
        """Render this entry as a single-line JSON string for the diff log."""
        payload: dict[str, object] = {
            "checked_at_utc": self.checked_at_utc.astimezone(UTC).isoformat(),
            "epoch_id": self.epoch_id,
            "pinned_hash": self.pinned_hash,
            "current_hash": self.current_hash,
            "outcome": self.outcome,
        }
        if self.run_metadata is not None:
            payload["run_metadata"] = dict(self.run_metadata)
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )


# --------------------------------------------------------------------------- #
# Run metadata + FreezeSkippedEntry — tick identification for the reconciler (plan 16-09).
# --------------------------------------------------------------------------- #

# The only environment variables a diff-log line copies run metadata from, with the key each is
# written under. GITHUB_* are runner defaults; PAPER_EVENT_SCHEDULE is set by the workflow from
# `github.event.schedule` (the cron string; empty on a manual run). Nothing else is ever read.
RUN_METADATA_ENV: tuple[tuple[str, str], ...] = (
    ("GITHUB_RUN_ID", "run_id"),
    ("GITHUB_RUN_ATTEMPT", "run_attempt"),
    ("GITHUB_EVENT_NAME", "event_name"),
    ("GITHUB_SHA", "commit"),
    ("PAPER_EVENT_SCHEDULE", "schedule"),
)
_RUN_METADATA_KEYS = frozenset(key for _, key in RUN_METADATA_ENV)


def read_run_metadata(environ: Mapping[str, str] | None = None) -> dict[str, str] | None:
    """Collect run metadata from the five named variables, or None when none is set.

    A variable that is present but empty is kept as an empty string: `github.event.schedule` is
    empty on a `workflow_dispatch` run and the line must say so rather than omit the key. A
    variable that is absent is omitted. With none of the five present the result is None and the
    line carries no `run_metadata` key, so lines written outside Actions are unchanged.
    """
    source = os.environ if environ is None else environ
    found = {key: source[name] for name, key in RUN_METADATA_ENV if name in source}
    return found or None


def _check_run_metadata(run_metadata: Mapping[str, str] | None) -> None:
    if run_metadata is None:
        return
    for key, value in run_metadata.items():
        if key not in _RUN_METADATA_KEYS:
            raise ValueError(f"run_metadata key {key!r} is not one of {sorted(_RUN_METADATA_KEYS)}")
        if not isinstance(value, str):
            raise ValueError(f"run_metadata[{key!r}] must be a str, got {type(value).__name__}")


@dataclass(frozen=True)
class FreezeSkippedEntry:
    """One JSONL line written when the freeze check has nothing to check (plan 16-09, D-21).

    The outcome is always "SKIPPED". It is written while the paper-start allowlist is empty: no
    parameter set is authorized, so the registry has nothing to be unchanged against. It is not a
    clean tick and proves nothing about any set; it only records that the check ran. A SKIPPED
    line is not counted against L-04 before the pin. `DiffLogEntry` keeps its two outcomes.
    """

    checked_at_utc: datetime
    reason: str
    run_metadata: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if self.checked_at_utc.tzinfo is None:
            raise ValueError("checked_at_utc must be UTC-aware")
        if not isinstance(self.reason, str) or self.reason.strip() == "":
            raise ValueError("reason must be a non-blank string")
        _check_run_metadata(self.run_metadata)

    @property
    def outcome(self) -> str:
        return "SKIPPED"

    def to_jsonl(self) -> str:
        """Render this entry as a single-line JSON string, in the style of `DiffLogEntry`."""
        payload: dict[str, object] = {
            "checked_at_utc": self.checked_at_utc.astimezone(UTC).isoformat(),
            "outcome": self.outcome,
            "reason": self.reason,
        }
        if self.run_metadata is not None:
            payload["run_metadata"] = dict(self.run_metadata)
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )


# --------------------------------------------------------------------------- #
# FreezeCheckOutcome — return type of check_registry_unchanged.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FreezeCheckOutcome:
    """Outcome of a freeze check tick (D-04).

    On a clean tick:
      - `current_epoch` equals `pinned_epoch` (the same epoch continues)
      - `halted_epoch` is None (no rollover)
      - `halted` is False, `halted_reason` is ""
      - `diff_entry.outcome` is "clean"

    On a rollover:
      - `current_epoch` is a new StreamEpoch with a new `epoch_id`
      - `halted_epoch` is a frozen copy of `pinned_epoch` with
        `evidence_claim_open=False` (the old pinned hash is preserved
        on this copy — D-04)
      - `halted` is True, `halted_reason` is "REGISTRY_DIFF"
      - `diff_entry.outcome` is "REGISTRY_DIFF"

    The `pinned_epoch` itself is never mutated (frozen dataclass); the
    halted state lives on the `halted_epoch` copy.
    """

    pinned_epoch: StreamEpoch
    current_epoch: StreamEpoch
    halted_epoch: StreamEpoch | None
    halted: bool
    halted_reason: str
    diff_entry: DiffLogEntry


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _require_utc_aware(value: datetime, field_name: str) -> None:
    """Reject naive datetimes loudly (WR-07)."""
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")


def _canonical_parameter_set_hash(
    *,
    strategy_id: str,
    strategy_version: str,
    parameter_set_id: str,
    parameters: dict[str, object],
) -> str:
    """Single canonical hash construction for parameter sets (WR-07).

    Both the pin path (`_load_parameter_set_with_root`) and the check
    path (`_recompute_parameter_set_hash`) build the registry hash
    here, so a future field added in one place cannot silently drift
    from the other and convert every clean tick into a phantom
    REGISTRY_DIFF rollover.
    """
    return sha256_hex(
        {
            "strategy_id": strategy_id,
            "strategy_version": strategy_version,
            "parameter_set_id": parameter_set_id,
            "parameters": parameters,
        }
    )


def _make_epoch_id(
    *,
    strategy_id: str,
    parameter_set_id: str,
    parameter_set_hash: str,
    opened_at_utc: datetime,
) -> str:
    """Derive the epoch_id from the pinned tuple (D-04 byte-stability).

    Two streams opened at different times against the same registry
    get distinct epoch_ids; two streams opened at the same time
    against the same registry get identical epoch_ids (prefix-
    invariance, D-02 determinism).
    """
    _require_utc_aware(opened_at_utc, "opened_at_utc")
    return sha256_hex(
        {
            "strategy_id": strategy_id,
            "parameter_set_id": parameter_set_id,
            "parameter_set_hash": parameter_set_hash,
            "opened_at_utc": opened_at_utc,
        }
    )


def _recompute_parameter_set_hash(
    *,
    strategy_id: str,
    parameter_set_id: str,
    registry_root: Path,
) -> str:
    """Re-read the registry TOML file and compute its canonical hash.

    Used by check_registry_unchanged to detect diffs against the
    pinned set without depending on the loaded ParameterSet's
    in-memory state. Reuses `_parse_and_validate` so the canonical
    hash matches what `load_parameter_set` would compute (D-04
    byte-stability).
    """
    _check_registry_segment(strategy_id, "strategy_id")
    _check_registry_segment(parameter_set_id, "parameter_set_id")
    path = registry_root / strategy_id / f"{parameter_set_id}.toml"
    if not path.is_file():
        raise FileNotFoundError(f"registry file missing: {path}")
    text = path.read_bytes().decode("utf-8")
    strategy_version, normalized_params = _parse_and_validate(
        text, path, strategy_id, parameter_set_id
    )
    return _canonical_parameter_set_hash(
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        parameter_set_id=parameter_set_id,
        parameters=normalized_params,
    )


def _read_registry_file(
    strategy_id: str,
    parameter_set_id: str,
    registry_root: Path,
) -> tuple[Path, str]:
    """Validate both ids as registry path segments, then read the set file exactly once.

    Returns the file path and its decoded text. Everything the gate decides about a set (hash,
    rationale verdict, allowlist match) is derived from this one read (review WR-05).
    """
    from src.domain.registry import UnregisteredParameterSet

    _check_registry_segment(strategy_id, "strategy_id")
    _check_registry_segment(parameter_set_id, "parameter_set_id")
    path = registry_root / strategy_id / f"{parameter_set_id}.toml"
    if not path.is_file():
        raise UnregisteredParameterSet(f"{strategy_id}/{parameter_set_id}")
    return path, path.read_bytes().decode("utf-8")


def resolve_registry_root(registry_root: Path | None = None) -> Path:
    """The registry root a call judges: the explicit override, else the live registry root.

    `src.domain.registry.REGISTRY_ROOT` is read here, at call time, and never copied at import
    (review IN-05): the gate and the loop therefore cannot hold two different bindings.
    """
    return registry_root if registry_root is not None else _registry.REGISTRY_ROOT


def _load_parameter_set_with_root(
    strategy_id: str,
    parameter_set_id: str,
    registry_root: Path,
) -> ParameterSet:
    """Load a ParameterSet from an explicit registry root.

    Mirrors `load_parameter_set` (src/domain/registry.py: same segment checks, same
    `_parse_and_validate`) but takes the root as an argument instead of reading the registry
    module global, so tests and `run_paper_tick` can pin the exact root they judge. The
    canonical hash construction matches what `load_parameter_set` computes for the same file
    (D-04 byte-stability).
    """
    path, text = _read_registry_file(strategy_id, parameter_set_id, registry_root)
    return _parameter_set_from_text(text, path, strategy_id, parameter_set_id)


def load_parameter_set_at_root(
    strategy_id: str,
    parameter_set_id: str,
    registry_root: Path,
) -> ParameterSet:
    """Public entry to `_load_parameter_set_with_root` for `run_paper_tick` (review IN-05)."""
    return _load_parameter_set_with_root(strategy_id, parameter_set_id, registry_root)


def _parameter_set_from_text(
    text: str,
    path: Path,
    strategy_id: str,
    parameter_set_id: str,
) -> ParameterSet:
    """Parse, validate and hash set-file text the caller already read."""
    strategy_version, normalized_params = _parse_and_validate(
        text, path, strategy_id, parameter_set_id
    )

    parameter_set_hash = _canonical_parameter_set_hash(
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        parameter_set_id=parameter_set_id,
        parameters=normalized_params,
    )
    return ParameterSet(
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        parameter_set_id=parameter_set_id,
        parameter_set_hash=parameter_set_hash,
        params=normalized_params,
    )


@dataclass(frozen=True)
class PaperAllowlistEntry:
    """One approved parameter set without rationale tables (checkpoint 15-17-01, Option B).

    The ids select candidate entries (lookup only, exact string equality). The only thing
    that admits a set is exact equality between `parameter_set_hash` and the hash computed
    from the parameter file through the registry parse path.
    """

    strategy_id: str
    """Strategy id the entry applies to (exact match, e.g. "trend-pullback")."""
    parameter_set_id: str
    """Parameter set id the entry applies to (exact match, e.g. "baseline-v3")."""
    parameter_set_hash: str
    """Full 64-hex lowercase parameter_set_hash the file must compute to."""
    purpose: str
    """Why this set may start a paper stream."""
    approved_at: str
    """ISO date of the user's approval."""
    basis: str
    """The user checkpoint and decision row that approved the entry."""

    def __post_init__(self) -> None:
        """Fail loudly on a malformed entry (review IN-01), naming the offending field.

        A malformed hash would never match and the user's approval would sit in the allowlist
        as a dead entry with only a generic refusal, so every field is checked at construction.
        """
        for field in dataclasses.fields(self):
            value = getattr(self, field.name)
            if not isinstance(value, str):
                raise TypeError(f"{field.name} must be a str, got {type(value).__name__}")
        if re.fullmatch(r"[0-9a-f]{64}", self.parameter_set_hash) is None:
            raise ValueError(
                "parameter_set_hash must be a 64-char lowercase hex SHA256 string, "
                f"got {self.parameter_set_hash!r}"
            )
        for text_field in ("strategy_id", "parameter_set_id", "purpose", "basis"):
            if getattr(self, text_field).strip() == "":
                raise ValueError(f"{text_field} must be a non-empty, non-blank string")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.approved_at) is None:
            raise ValueError(
                f"approved_at must be an ISO date YYYY-MM-DD, got {self.approved_at!r}"
            )
        try:
            date.fromisoformat(self.approved_at)
        except ValueError as exc:
            raise ValueError(
                f"approved_at must be a real ISO date YYYY-MM-DD, got {self.approved_at!r}"
            ) from exc


# Checkpoint 15-17-01, Option B (user decision of 2026-10-07): the allowlist shipped EMPTY.
# Checkpoint G4-021 (user decision of 2026-10-16, decisions/16-DEC-G4-021.md, option
# exact-entry-pin) added the single entry below, the candidate designated in plan 16-48.
# Any other entry, or an edit of this one, needs a new user checkpoint, a D054 update and an
# update of the pin test in tests/test_paper_start_gate.py. An entry never replaces the
# rationale and PLACEHOLDER check of a set that has rationale tables (D-27 unchanged).
PAPER_START_ALLOWLIST: tuple[PaperAllowlistEntry, ...] = (
    PaperAllowlistEntry(
        strategy_id="trend-pullback",
        parameter_set_id="research-run-1-a01",
        parameter_set_hash=("6f42f70e7e7a107b1be02fc4079fbb70f1408b4307099aa253bd93ebdbce6d87"),
        purpose=(
            "Paper (SHADOW) trial soak của ứng viên đã đăng ký trước đầu tiên của research run 1"
        ),
        approved_at="2026-10-16",
        basis=(
            "Checkpoint G4-021 (decisions/16-DEC-G4-021.md), chỉ định ứng viên "
            "(decisions/16-DEC-candidate.md), D054 mục (i)"
        ),
    ),
)


def allowlist_entries() -> tuple[PaperAllowlistEntry, ...]:
    """The approved paper-start allowlist, read at call time (plan 16-09).

    This and `find_allowlist_entry` are the only accessors other code may use; the runtime
    (plan 16-22) and the freeze CLI go through them and never name the tuple itself, so the
    AST guard in tests/test_paper_start_gate.py keeps the name inside this module.
    """
    return PAPER_START_ALLOWLIST


def find_allowlist_entry(strategy_id: str, parameter_set_id: str) -> PaperAllowlistEntry | None:
    """The allowlist entry for exactly these ids, or None when none is listed.

    Lookup only, by exact string equality; the entry's hash is what admits a set, not this call.

    Raises:
        ValueError: more than one entry lists these ids. Nothing is guessed (fail closed).
    """
    matches = [
        entry
        for entry in allowlist_entries()
        if entry.strategy_id == strategy_id and entry.parameter_set_id == parameter_set_id
    ]
    if len(matches) > 1:
        raise ValueError(
            f"ambiguous allowlist: {len(matches)} entries list {strategy_id}/{parameter_set_id}"
        )
    return matches[0] if matches else None


def require_bool_flag(value: object) -> None:
    """Fail closed on a non-bool `allow_unrationalized` (review WR-01).

    A config or CLI string such as "False" or an int is truthy and would silently switch the
    gate off, so only a real bool is accepted; the gate is bypassed only by exactly `True`.
    """
    if not isinstance(value, bool):
        raise TypeError(
            f"allow_unrationalized must be a bool, got {type(value).__name__} ({value!r})"
        )


def _has_rationale_tables(text: str) -> bool:
    """True when the set's TOML document has a top-level `rationale` key (even if malformed)."""
    return "rationale" in tomllib.loads(text)


def _require_allowlisted(
    *, strategy_id: str, parameter_set_id: str, parameter_set_hash: str
) -> None:
    """Admit a set without rationale tables only on an exact-hash allowlist entry."""
    allowlist = PAPER_START_ALLOWLIST  # read at call time, never copied at import
    candidates = [
        entry
        for entry in allowlist
        if entry.strategy_id == strategy_id and entry.parameter_set_id == parameter_set_id
    ]
    if any(entry.parameter_set_hash == parameter_set_hash for entry in candidates):
        return
    message = (
        f"{strategy_id}/{parameter_set_id}: missing rationale tables and "
        f"not in the approved allowlist (parameter_set_hash {parameter_set_hash})"
    )
    if candidates:
        listed = ", ".join(entry.parameter_set_hash for entry in candidates)
        message += f"; allowlist lists hash {listed} for these ids, not the file's hash"
    elif not allowlist:
        message += (
            "; the approved allowlist is empty (checkpoint 15-17-01, Option B), so no set "
            "without rationale tables may start a paper stream; this is the decided safe "
            "state, not a system fault"
        )
    raise UnrationalizedParameterSet(message)


def _require_rationalized(
    path: Path,
    text: str,
    *,
    strategy_id: str,
    parameter_set_id: str,
    parameter_set_hash: str,
) -> None:
    """Refuse a set whose rationale is incomplete, that carries PLACEHOLDER keys, or that has
    no rationale tables and no exact-hash allowlist entry (D-16, D-27)."""
    if not _has_rationale_tables(text):
        _require_allowlisted(
            strategy_id=strategy_id,
            parameter_set_id=parameter_set_id,
            parameter_set_hash=parameter_set_hash,
        )
        return
    problems = check_rationale_text(text, path)
    placeholders = placeholder_keys_text(text)
    if not problems and not placeholders:
        return
    parts: list[str] = []
    if problems:
        parts.append("rationale problems: " + "; ".join(problems))
    if placeholders:
        parts.append("PLACEHOLDER keys: " + ", ".join(placeholders))
    raise UnrationalizedParameterSet(f"{path.parent.name}/{path.stem}: " + " | ".join(parts))


# --------------------------------------------------------------------------- #
# pin_stream_epoch — pin (parameterSetId, parameterSetHash); a per-call gate.
# --------------------------------------------------------------------------- #


def pin_stream_epoch(
    *,
    strategy_id: str,
    parameter_set_id: str,
    opened_at_utc: datetime,
    cost_model: CostModel | None = None,
    registry_root: Path | None = None,
    allow_unrationalized: bool = False,
) -> StreamEpoch:
    """Pin a parameter set (D-04) and judge it against the paper-start policy.

    This is a per-call gate: it persists nothing and carries no state between calls
    (`run_paper_tick` calls it on every tick). The runtime of plan 16-22 adds a
    once-per-process start gate and pins the epoch once.

    Loads the registry ParameterSet, builds the CostModel from the
    registry's cost-key slice, and runs the 07.1 binding gate. Returns
    the StreamEpoch carrying the pinned tuple.

    Args:
        strategy_id: The strategy id (e.g. "trend-pullback").
        parameter_set_id: The parameter set id (e.g. "baseline-v3").
        opened_at_utc: UTC-aware datetime marking when the stream
            epoch opened (used to derive the epoch_id).
        cost_model: Optional caller-supplied CostModel to verify
            against the registry slice. If None, a CostModel is
            built from the registry's cost-key slice (trivially
            binding).
        registry_root: Optional registry root override. Defaults to
            `src.domain.registry.REGISTRY_ROOT`, read at call time (review IN-05), so a
            caller that loaded the set from that root judges the same file here.
        allow_unrationalized: Test-only escape hatch for pinning legacy
            sets that carry no `[rationale.<key>]` tables. The default is
            strict: a set with a missing or incomplete rationale, or with
            any PLACEHOLDER key, cannot be pinned for paper (D-16, D-27).
            Tests only. src/ never sets it to True (tests/test_paper_start_gate.py
            enforces this); run_paper_tick passes its own keyword through, default False.

    Raises:
        UnregisteredParameterSet: file does not exist.
        UnrationalizedParameterSet: the set's rationale is missing or
            incomplete, or at least one key has basis PLACEHOLDER, or the
            set has no rationale tables and no exact-hash
            PAPER_START_ALLOWLIST entry admits it, and
            `allow_unrationalized` is False.
        CostModelBindingMismatch: caller-supplied cost model does not
            bind the registry (per 07.1 D-01).
        KeyError: missing cost-slice keys in the registry (fail
            closed, never translated — 07.1 D-02).
        ValueError: naive opened_at_utc (WR-07).
    """
    require_bool_flag(allow_unrationalized)
    _require_utc_aware(opened_at_utc, "opened_at_utc")
    root = resolve_registry_root(registry_root)
    path, text = _read_registry_file(strategy_id, parameter_set_id, root)
    parameter_set = _parameter_set_from_text(text, path, strategy_id, parameter_set_id)

    if allow_unrationalized is not True:
        _require_rationalized(
            path,
            text,
            strategy_id=strategy_id,
            parameter_set_id=parameter_set_id,
            parameter_set_hash=parameter_set.parameter_set_hash,
        )

    # Build the cost model from the registry's cost-key slice. This
    # propagates bare KeyError from build_cost_model if any slice key
    # is missing (fail closed, never translated — 07.1 D-02). The
    # build is the registry-binding check — calling build_cost_model
    # on the registry slice always succeeds if the keys are present,
    # so we just call it here to surface the KeyError path.
    registry_slice = cost_slice(parameter_set.params)
    build_cost_model(registry_slice)

    # If the caller supplied a cost model, verify it binds the
    # registry (07.1 D-01).
    if cost_model is not None:
        assert_cost_model_binds_registry(parameter_set, cost_model)

    epoch_id = _make_epoch_id(
        strategy_id=strategy_id,
        parameter_set_id=parameter_set_id,
        parameter_set_hash=parameter_set.parameter_set_hash,
        opened_at_utc=opened_at_utc,
    )

    return StreamEpoch(
        epoch_id=epoch_id,
        strategy_id=strategy_id,
        parameter_set_id=parameter_set_id,
        parameter_set_hash=parameter_set.parameter_set_hash,
        opened_at_utc=opened_at_utc,
        evidence_claim_open=True,
    )


# --------------------------------------------------------------------------- #
# check_registry_unchanged — re-read the registry and compare hashes.
# --------------------------------------------------------------------------- #


def check_registry_unchanged(
    pinned_epoch: StreamEpoch,
    *,
    registry_root: Path | None = None,
    diff_log_path: Path | None = None,
    now_utc: datetime | None = None,
    run_metadata: Mapping[str, str] | None = None,
) -> FreezeCheckOutcome:
    """Re-read the registry and compare canonical hashes (D-04).

    On a clean tick (current_hash == pinned_hash), appends one JSONL
    line with outcome "clean" and returns FreezeCheckOutcome with
    current_epoch == pinned_epoch and halted_epoch is None.

    On a rollover (current_hash != pinned_hash), appends one JSONL line
    with outcome "REGISTRY_DIFF", returns FreezeCheckOutcome with a
    new current_epoch (epoch_id derived from the new hash + now_utc)
    and a halted_epoch (frozen copy of pinned_epoch with
    evidence_claim_open=False). The pinned_epoch itself is never
    mutated (frozen dataclass), so its parameter_set_hash string is
    preserved on the halted copy (D-04).

    Args:
        pinned_epoch: The StreamEpoch to check against.
        registry_root: Optional registry root override (for tests).
        diff_log_path: Optional path to append the JSONL diff entry.
            If None, no file is written (pure check).
        now_utc: UTC-aware datetime marking the check time. If None,
            uses datetime.now(UTC). Defaults to wall-clock for
            soak-runtime use.
        run_metadata: Optional run identity (see `read_run_metadata`) written on the
            diff-log line; None writes the line exactly as before plan 16-09.
    """
    root = resolve_registry_root(registry_root)
    if now_utc is None:
        now_utc = datetime.now(UTC)
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be UTC-aware, got naive datetime")

    # Re-read the registry file and compute its current hash.
    # The pinned_epoch carries strategy_id (set at pin time), so we
    # don't need to auto-detect it from the registry root.
    current_hash = _recompute_parameter_set_hash(
        strategy_id=pinned_epoch.strategy_id,
        parameter_set_id=pinned_epoch.parameter_set_id,
        registry_root=root,
    )

    if current_hash == pinned_epoch.parameter_set_hash:
        # Clean tick: keep the epoch, append clean entry.
        diff_entry = DiffLogEntry(
            checked_at_utc=now_utc,
            epoch_id=pinned_epoch.epoch_id,
            pinned_hash=pinned_epoch.parameter_set_hash,
            current_hash=current_hash,
            outcome="clean",
            run_metadata=run_metadata,
        )
        if diff_log_path is not None:
            _append_diff_entry(diff_log_path, diff_entry)
        return FreezeCheckOutcome(
            pinned_epoch=pinned_epoch,
            current_epoch=pinned_epoch,
            halted_epoch=None,
            halted=False,
            halted_reason="",
            diff_entry=diff_entry,
        )

    # Rollover: open a new epoch, halt the old one.
    new_epoch_id = _make_epoch_id(
        strategy_id=pinned_epoch.strategy_id,
        parameter_set_id=pinned_epoch.parameter_set_id,
        parameter_set_hash=current_hash,
        opened_at_utc=now_utc,
    )
    new_epoch = StreamEpoch(
        epoch_id=new_epoch_id,
        strategy_id=pinned_epoch.strategy_id,
        parameter_set_id=pinned_epoch.parameter_set_id,
        parameter_set_hash=current_hash,
        opened_at_utc=now_utc,
        evidence_claim_open=True,
    )
    halted_epoch = dataclasses.replace(pinned_epoch, evidence_claim_open=False)
    diff_entry = DiffLogEntry(
        checked_at_utc=now_utc,
        epoch_id=pinned_epoch.epoch_id,
        pinned_hash=pinned_epoch.parameter_set_hash,
        current_hash=current_hash,
        outcome="REGISTRY_DIFF",
        run_metadata=run_metadata,
    )
    if diff_log_path is not None:
        _append_diff_entry(diff_log_path, diff_entry)
    return FreezeCheckOutcome(
        pinned_epoch=pinned_epoch,
        current_epoch=new_epoch,
        halted_epoch=halted_epoch,
        halted=True,
        halted_reason="REGISTRY_DIFF",
        diff_entry=diff_entry,
    )


def _append_diff_entry(path: Path, entry: DiffLogEntry | FreezeSkippedEntry) -> None:
    """Append one JSONL line to the diff log, creating parent dirs.

    Append-only history (D-04): the file is never rewritten or
    truncated. Parent directories are created on first write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(entry.to_jsonl() + "\n")


# --------------------------------------------------------------------------- #
# CLI — run_check_cli invoked by the scheduled workflow.
# --------------------------------------------------------------------------- #


def write_pinned_state(epoch: StreamEpoch, path: Path) -> None:
    """Write the StreamEpoch to a pinned-state JSON file.

    The CLI loads pinned state from this file on each tick. The file
    lives at the operator-configurable pinned_state_path (default
    `logs/paper/pinned_epoch.json`).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "epoch_id": epoch.epoch_id,
        "strategy_id": epoch.strategy_id,
        "parameter_set_id": epoch.parameter_set_id,
        "parameter_set_hash": epoch.parameter_set_hash,
        "opened_at_utc": epoch.opened_at_utc.astimezone(UTC).isoformat(),
        "evidence_claim_open": epoch.evidence_claim_open,
    }
    path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")


def load_pinned_state(path: Path) -> StreamEpoch:
    """Load a StreamEpoch from a pinned-state JSON file.

    Raises FileNotFoundError if the file does not exist.
    """
    if not path.is_file():
        raise FileNotFoundError(f"pinned-state file missing: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return StreamEpoch(
        epoch_id=raw["epoch_id"],
        strategy_id=raw["strategy_id"],
        parameter_set_id=raw["parameter_set_id"],
        parameter_set_hash=raw["parameter_set_hash"],
        opened_at_utc=_parse_utc_aware(raw["opened_at_utc"]),
        evidence_claim_open=bool(raw.get("evidence_claim_open", True)),
    )


def _parse_utc_aware(raw: str) -> datetime:
    """Parse an ISO-8601 string into a UTC-aware datetime."""
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None:
        raise ValueError(f"naive datetime in pinned-state file: {raw!r}")
    return value.astimezone(UTC)


def run_check_cli(
    *,
    strategy_id: str,
    parameter_set_id: str,
    pinned_state_path: Path,
    diff_log_path: Path,
    registry_root: Path | None = None,
    now_utc: datetime | None = None,
    expected_hash: str | None = None,
    run_metadata: Mapping[str, str] | None = None,
) -> int:
    """Run one tick of the freeze check (CLI entry point).

    Loads the pinned epoch from `pinned_state_path`, re-reads the
    registry, appends one JSONL entry to `diff_log_path`, and on
    rollover writes the new pinned state.

    The CLI's `--strategy-id/--parameter-set-id` must match the pinned
    file (WR-15): checking pair B against pair A's state is a silent
    wrong-answer success without this gate.

    When `expected_hash` is given (the allowlist mode, plan 16-09) the pinned state must
    also carry exactly that hash: a state pinned to any other hash than the one the user
    approved is refused with 1 and no line is written.

    Returns:
        0 on a clean tick.
        3 on a REGISTRY_DIFF rollover (CR-06: distinct from success
          so the workflow can page/alert instead of reporting green).
        2 if the pinned state file is missing (soak not started yet
          or the state file was deleted).
        1 on any other error (including a strategy-id mismatch).
    """
    try:
        pinned_epoch = load_pinned_state(pinned_state_path)
    except FileNotFoundError:
        return 2

    if strategy_id != pinned_epoch.strategy_id or parameter_set_id != pinned_epoch.parameter_set_id:
        log.error(
            "paper.freeze.cli_id_mismatch",
            cli_strategy_id=strategy_id,
            cli_parameter_set_id=parameter_set_id,
            pinned_strategy_id=pinned_epoch.strategy_id,
            pinned_parameter_set_id=pinned_epoch.parameter_set_id,
        )
        return 1

    if expected_hash is not None and pinned_epoch.parameter_set_hash != expected_hash:
        log.error(
            "paper.freeze.cli_pinned_hash_not_approved",
            strategy_id=pinned_epoch.strategy_id,
            parameter_set_id=pinned_epoch.parameter_set_id,
            pinned_hash=pinned_epoch.parameter_set_hash,
            approved_hash=expected_hash,
        )
        return 1

    outcome = check_registry_unchanged(
        pinned_epoch,
        registry_root=registry_root,
        diff_log_path=diff_log_path,
        now_utc=now_utc,
        run_metadata=run_metadata,
    )

    # On rollover, persist the new pinned state so the next tick
    # checks against the new hash.
    if outcome.halted:
        write_pinned_state(outcome.current_epoch, pinned_state_path)
        return 3

    return 0


# --------------------------------------------------------------------------- #
# CLI __main__ — `python -m src.paper.freeze --check ...`
# --------------------------------------------------------------------------- #


def run_allowlist_check_cli(
    *,
    pinned_state_path: Path,
    diff_log_path: Path,
    registry_root: Path | None = None,
    run_metadata: Mapping[str, str] | None = None,
    now_utc: datetime | None = None,
) -> int:
    """Run one freeze-check tick for whatever the paper-start allowlist authorizes (D-21, L-01).

    The ids come from the allowlist, never from the caller, so no fallback set can be named.

    Returns:
        0 when the allowlist is empty (one SKIPPED line is appended; nothing is pinned or
          checked, and no clean line is ever written for it).
        1 when the allowlist is not usable (more than one entry: "ambiguous allowlist").
        Otherwise the exit code of `run_check_cli` for the single listed entry.
    """
    entries = allowlist_entries()
    if len(entries) == 0:
        when = datetime.now(UTC) if now_utc is None else now_utc
        _append_diff_entry(
            diff_log_path,
            FreezeSkippedEntry(
                checked_at_utc=when, reason="allowlist empty", run_metadata=run_metadata
            ),
        )
        return 0
    if len(entries) > 1:
        log.error(
            "paper.freeze.cli_ambiguous_allowlist",
            reason="ambiguous allowlist",
            entries=len(entries),
        )
        return 1
    entry = entries[0]
    return run_check_cli(
        strategy_id=entry.strategy_id,
        parameter_set_id=entry.parameter_set_id,
        pinned_state_path=pinned_state_path,
        diff_log_path=diff_log_path,
        registry_root=registry_root,
        now_utc=now_utc,
        expected_hash=entry.parameter_set_hash,
        run_metadata=run_metadata,
    )


def _cli_main(argv: list[str] | None = None) -> int:
    """Parse argv and dispatch to the check subcommand.

    Usage:
      python -m src.paper.freeze --check \\
          --strategy-id trend-pullback \\
          --parameter-set-id baseline-v3 \\
          --diff-log logs/paper/registry_diff.jsonl \\
          [--pinned-state logs/paper/pinned_epoch.json] \\
          [--registry-root params]

      python -m src.paper.freeze --check --from-allowlist \\
          --diff-log logs/paper/registry_diff.jsonl \\
          [--pinned-state logs/paper/pinned_epoch.json] \\
          [--registry-root params]

    With `--from-allowlist` the ids come from the paper-start allowlist and the two id flags are
    forbidden; without it both are required (today's behaviour).
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="src.paper.freeze",
        description="Paper freeze monitor CLI (Phase 7, plan 07-04).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run one freeze-check tick (required).",
    )
    parser.add_argument(
        "--from-allowlist",
        action="store_true",
        help=(
            "Check the parameter set the paper-start allowlist authorizes; SKIPPED while it is "
            "empty. Forbids --strategy-id and --parameter-set-id."
        ),
    )
    parser.add_argument(
        "--strategy-id",
        default=None,
        help="Strategy id (e.g. trend-pullback); required without --from-allowlist.",
    )
    parser.add_argument(
        "--parameter-set-id",
        default=None,
        help="Parameter set id (e.g. baseline-v3); required without --from-allowlist.",
    )
    parser.add_argument(
        "--diff-log",
        type=Path,
        required=True,
        help="Path to the JSONL diff-log file.",
    )
    parser.add_argument(
        "--pinned-state",
        type=Path,
        default=Path("logs/paper/pinned_epoch.json"),
        help="Path to the pinned-state JSON file (default: logs/paper/pinned_epoch.json).",
    )
    parser.add_argument(
        "--registry-root",
        type=Path,
        default=None,
        help="Registry root directory (default: src.domain.registry.REGISTRY_ROOT).",
    )
    args = parser.parse_args(argv)

    if not args.check:
        parser.error("--check is required")

    if args.from_allowlist:
        if args.strategy_id is not None or args.parameter_set_id is not None:
            parser.error("--from-allowlist forbids --strategy-id and --parameter-set-id")
        return run_allowlist_check_cli(
            pinned_state_path=args.pinned_state,
            diff_log_path=args.diff_log,
            registry_root=args.registry_root,
            run_metadata=read_run_metadata(),
            now_utc=None,
        )

    if args.strategy_id is None or args.parameter_set_id is None:
        parser.error("--strategy-id and --parameter-set-id are required without --from-allowlist")

    return run_check_cli(
        strategy_id=args.strategy_id,
        parameter_set_id=args.parameter_set_id,
        pinned_state_path=args.pinned_state,
        diff_log_path=args.diff_log,
        registry_root=args.registry_root,
        now_utc=None,
        run_metadata=read_run_metadata(),
    )


__all__ = [
    "StreamEpoch",
    "DiffLogEntry",
    "FreezeSkippedEntry",
    "FreezeCheckOutcome",
    "pin_stream_epoch",
    "check_registry_unchanged",
    "write_pinned_state",
    "load_pinned_state",
    "run_check_cli",
    "run_allowlist_check_cli",
    "allowlist_entries",
    "find_allowlist_entry",
    "read_run_metadata",
    "_cli_main",
]
