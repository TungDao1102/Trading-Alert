"""Runtime state port: deterministic, replay-safe records that survive a restart (plan 16-16).

The paper runtime writes every record that must survive a restart or explain a gap through ONE
port (D-04, D-06, L-04 "no duplicate signal and no missing journal row"): the pinned epoch, the
last processed close per (symbol, interval), gaps, heartbeats and runtime markers.

The port also carries the instance lease (plan 16-55, B1-WR-07): one paper runtime per database,
taken before any record; the PostgreSQL port holds it as a session advisory lock.

Pure module: stdlib and the pure domain helpers, no SQLAlchemy and no adapter (the PostgreSQL
implementation lives in `src/persistence/paper_runtime_state.py`, per the Q-J decision
"journal-only": every record is a journal event, no second persistence mechanism).

Ids are a pure function of the record key, never of the wall clock (research Pattern 3 and
Pitfall P11): `correlated_event_id(prefix="paper", correlation_id=..., ...)` over

- bar-keyed records (PAPER_BAR_PROCESSED, PAPER_REPLAY_INPUTS, PAPER_GAP):
  `paper:<epoch>:<symbol>:<interval>:<close_ms>`. A bar record's close is its `occurred_at_utc`
  (the replay-inputs record of plan 16-51 is keyed like its heartbeat; the event type in the hashed
  material keeps the two ids apart); a gap's close is the `expected_close_utc` in its payload, so a
  gap detected twice (before and after a restart) is the same record;
- PAPER_TICK_STATS: `paper:<epoch>:tick:<at_ms>:<batch_seq>` (the tick time is the injected time;
  `batch_seq` is a per-process counter carried in the payload, research P20 and A10);
- PAPER_HISTORY_BARS (plan 16-51): `paper:<epoch>:history:<at_ms>:<history_seq>` (the injected
  tick time and a per-pipeline counter carried in the payload, read under the same rule as
  `batch_seq`);
- every other runtime marker: `paper:<epoch>:runtime:<at_ms>`.

The event type is part of the hashed material, so two types at the same instant never collide.
Replaying a record is a no-op; the same id with different content (event type, pair or payload)
is a `RuntimeRecordConflict`. `occurred_at_utc` is not compared on replay, which matches the
journal store (a redelivery carries a new delivery time with the same identity).

The payload is normalised once at construction with the project's canonical scalar policy
(`src.domain.canonical`): `Decimal` and `datetime` become text, floats are refused, nested
mappings and sequences are frozen. In-memory and PostgreSQL records therefore round-trip to
equal values.

Payload-key contract read by `src/paper/coverage.py` (`RuntimeRecordLike`): PAPER_BAR_PROCESSED
`source` and `tick_time_utc`; PAPER_GAP `expected_close_utc` and `reason`; HEALTH_STATE_CHANGED
`state` and `reason`; PAPER_TICK_STATS `batch_seq`, `duration_ms`, `queue_depth_before`,
`dropped_total`, `dropped_by_reason`. The payloads of PAPER_REPLAY_INPUTS and PAPER_HISTORY_BARS
are read only by the trial evaluator (`src/paper/replay_inputs.py`, `src/paper/exit_criteria.py`);
the id rules above read `history_seq` of the latter and nothing of the former.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any, Protocol

from src.domain.canonical import canonical_bytes, canonical_scalars
from src.domain.journal import correlated_event_id
from src.paper.vocabulary import RuntimeEventType

EVENT_ID_PREFIX = "paper"
EVENT_ID_STEP = "v1"
ENTITY_TYPE = "PaperRuntime"
RUNTIME_ENTITY_ID = "runtime"

_EPOCH_ORIGIN = datetime(1970, 1, 1, tzinfo=UTC)
_ONE_MS = timedelta(milliseconds=1)

# Limits that keep every derived journal column inside its width (correlation_id is 128 wide:
# "paper:" + 64 + ":" + 32 + ":" + 8 + ":" + 13 digits = 126).
_MAX_EPOCH_ID_LENGTH = 64
_MAX_SYMBOL_LENGTH = 32
_MAX_INTERVAL_LENGTH = 8

_BAR_KEYED = frozenset(
    {
        RuntimeEventType.PAPER_BAR_PROCESSED,
        RuntimeEventType.PAPER_REPLAY_INPUTS,
        RuntimeEventType.PAPER_GAP,
    }
)
# Bar-keyed types whose close is the record's own `occurred_at_utc` (a gap names its close).
_CLOSE_FROM_TIME = frozenset(
    {RuntimeEventType.PAPER_BAR_PROCESSED, RuntimeEventType.PAPER_REPLAY_INPUTS}
)
_MARKER_EVENTS = frozenset({RuntimeEventType.RUNTIME_START, RuntimeEventType.RUNTIME_STOP})

# Same-instant order of the two markers, matching `src/paper/coverage.py`: a STOP at the same
# instant as a START closes the old run before the new one opens, so the START is the later one.
_MARKER_ORDER: Mapping[RuntimeEventType, int] = {
    RuntimeEventType.RUNTIME_STOP: 0,
    RuntimeEventType.RUNTIME_START: 1,
}


class RuntimeRecordConflict(Exception):
    """The same record id was recorded again with different content (fail loudly)."""


def _plain(value: object) -> object:
    """Mappings to dicts (text keys only) and sequences to lists, recursively."""
    if isinstance(value, Mapping):
        out: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"payload key must be text, got {type(key).__name__}")
            out[key] = _plain(item)
        return out
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _check_text(name: str, value: object, max_length: int) -> str:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{name} must be a non-empty string")
    if ":" in value:
        raise ValueError(f"{name} must not contain ':'")
    if len(value) > max_length:
        raise ValueError(f"{name} must be at most {max_length} characters")
    return value


@dataclass(frozen=True)
class RuntimeRecord:
    """One runtime record: what happened, in which epoch, for which pair, at what time.

    `occurred_at_utc` is the bar close for a PAPER_BAR_PROCESSED record (use `bar_processed`),
    and the injected event time for every other record. `symbol` and `interval` are given
    together (bar-keyed records need them) or both omitted (runtime-wide markers).
    """

    event_type: RuntimeEventType
    epoch_id: str
    occurred_at_utc: datetime
    symbol: str | None = None
    interval: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict, hash=False)
    payload_json: str = field(init=False, repr=False, compare=False, hash=False)

    def __post_init__(self) -> None:
        if not isinstance(self.event_type, RuntimeEventType):
            raise ValueError("event_type must be a RuntimeEventType")
        _check_text("epoch_id", self.epoch_id, _MAX_EPOCH_ID_LENGTH)
        if self.occurred_at_utc.tzinfo is None or self.occurred_at_utc.utcoffset() != timedelta(0):
            raise ValueError("occurred_at_utc must be UTC-aware (offset zero)")
        if (self.symbol is None) != (self.interval is None):
            raise ValueError("symbol and interval must be given together")
        if self.symbol is not None and self.interval is not None:
            _check_text("symbol", self.symbol, _MAX_SYMBOL_LENGTH)
            _check_text("interval", self.interval, _MAX_INTERVAL_LENGTH)
        if not isinstance(self.payload, Mapping):
            raise ValueError("payload must be a mapping")
        canonical = canonical_scalars(_plain(self.payload))
        object.__setattr__(self, "payload_json", canonical_bytes(canonical).decode("ascii"))
        object.__setattr__(self, "payload", _freeze(canonical))

    @classmethod
    def bar_processed(
        cls,
        *,
        epoch_id: str,
        symbol: str,
        interval: str,
        close_time_utc: datetime,
        payload: Mapping[str, Any] | None = None,
    ) -> RuntimeRecord:
        """A PAPER_BAR_PROCESSED record whose time is the bar close, not the recording time."""
        return cls(
            event_type=RuntimeEventType.PAPER_BAR_PROCESSED,
            epoch_id=epoch_id,
            occurred_at_utc=close_time_utc,
            symbol=symbol,
            interval=interval,
            payload=payload if payload is not None else {},
        )


def _ms(moment: datetime) -> int:
    """Whole milliseconds since the Unix epoch (floor), integer arithmetic only."""
    return (moment.astimezone(UTC) - _EPOCH_ORIGIN) // _ONE_MS


def _payload_time_ms(record: RuntimeRecord, key: str) -> int:
    raw = record.payload.get(key)
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            raise ValueError(
                f"{record.event_type.value} payload {key} is not an ISO time"
            ) from None
        if parsed.tzinfo is None:
            raise ValueError(f"{record.event_type.value} payload {key} must be UTC-aware")
        return _ms(parsed)
    raise ValueError(f"{record.event_type.value} needs payload {key} (an ISO UTC time)")


def _batch_seq(record: RuntimeRecord) -> int:
    seq = record.payload.get("batch_seq")
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
        raise ValueError("PAPER_TICK_STATS needs payload batch_seq (a non-negative integer)")
    return seq


def _history_seq(record: RuntimeRecord) -> int:
    seq = record.payload.get("history_seq")
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
        raise ValueError("PAPER_HISTORY_BARS needs payload history_seq (a non-negative integer)")
    return seq


def runtime_correlation_prefix(epoch_id: str) -> str:
    """Prefix shared by every correlation id of one epoch: `paper:<epoch>:`."""
    return f"{EVENT_ID_PREFIX}:{_check_text('epoch_id', epoch_id, _MAX_EPOCH_ID_LENGTH)}:"


def runtime_entity_id(record: RuntimeRecord) -> str:
    """`<symbol>:<interval>` for a pair-scoped record, `runtime` for a runtime-wide one."""
    if record.symbol is not None and record.interval is not None:
        return f"{record.symbol}:{record.interval}"
    return RUNTIME_ENTITY_ID


def runtime_correlation_id(record: RuntimeRecord) -> str:
    """The deterministic correlation id of a record (see the module docstring)."""
    prefix = runtime_correlation_prefix(record.epoch_id)
    if record.event_type in _BAR_KEYED:
        if record.symbol is None or record.interval is None:
            raise ValueError(f"{record.event_type.value} needs symbol and interval")
        if record.event_type in _CLOSE_FROM_TIME:
            close_ms = _ms(record.occurred_at_utc)
        else:
            close_ms = _payload_time_ms(record, "expected_close_utc")
        return f"{prefix}{record.symbol}:{record.interval}:{close_ms}"
    if record.event_type is RuntimeEventType.PAPER_TICK_STATS:
        return f"{prefix}tick:{_ms(record.occurred_at_utc)}:{_batch_seq(record)}"
    if record.event_type is RuntimeEventType.PAPER_HISTORY_BARS:
        return f"{prefix}history:{_ms(record.occurred_at_utc)}:{_history_seq(record)}"
    return f"{prefix}runtime:{_ms(record.occurred_at_utc)}"


def runtime_event_id(record: RuntimeRecord) -> str:
    """Deterministic `journal_event_id` of a record: a pure function of its key, no clock."""
    return correlated_event_id(
        prefix=EVENT_ID_PREFIX,
        correlation_id=runtime_correlation_id(record),
        event_type=record.event_type.value,
        entity_id=runtime_entity_id(record),
        step=EVENT_ID_STEP,
    )


def same_content(left: RuntimeRecord, right: RuntimeRecord) -> bool:
    """Replay identity: event type, epoch, pair and payload (not the delivery time)."""
    return (
        left.event_type is right.event_type
        and left.epoch_id == right.epoch_id
        and left.symbol == right.symbol
        and left.interval == right.interval
        and left.payload_json == right.payload_json
    )


def record_sort_key(record: RuntimeRecord) -> tuple[datetime, int, str, str, str, str]:
    """Total order of the records of one epoch: time, marker order, then stable text keys."""
    return (
        record.occurred_at_utc,
        _MARKER_ORDER.get(record.event_type, 2),
        record.event_type.value,
        record.symbol or "",
        record.interval or "",
        record.payload_json,
    )


def latest_marker(records: Sequence[RuntimeRecord]) -> RuntimeRecord | None:
    """The last RUNTIME_START or RUNTIME_STOP of the given records, or None."""
    markers = [r for r in records if r.event_type in _MARKER_EVENTS]
    return max(markers, key=record_sort_key) if markers else None


def last_closes(records: Sequence[RuntimeRecord]) -> dict[tuple[str, str], datetime]:
    """The latest PAPER_BAR_PROCESSED close per (symbol, interval)."""
    out: dict[tuple[str, str], datetime] = {}
    for record in records:
        if record.event_type is not RuntimeEventType.PAPER_BAR_PROCESSED:
            continue
        if record.symbol is None or record.interval is None:
            continue
        pair = (record.symbol, record.interval)
        if pair not in out or record.occurred_at_utc > out[pair]:
            out[pair] = record.occurred_at_utc
    return out


# --------------------------------------------------------------------------- #
# The instance lease: one paper runtime per database (plan 16-55, review B1-WR-07).
# --------------------------------------------------------------------------- #

# The scope every paper runtime and every pin leases. One scope per database, not one per epoch:
# the epoch id hashes the opening time, so a pin learns its epoch only by pinning, and the lease
# must already be held then (before the pin branch and before any record). Only the latest pin is
# ever runnable (REV-18), so one runtime per database is one runtime per epoch, and a pin can
# never run beside any runtime of the database.
INSTANCE_LEASE_SCOPE = "paper-runtime"

_LEASE_KEY_DOMAIN = b"trading-alert:paper-runtime-instance-lease:"


def instance_lease_key(scope: str) -> int:
    """A stable non-negative 63-bit key of a lease scope (the first 8 bytes of a SHA-256).

    PostgreSQL advisory locks take a signed 64-bit key; the top bit is cleared so the key and its
    two 32-bit halves in `pg_locks` (classid, objid) are the same on every platform.
    """
    digest = hashlib.sha256(_LEASE_KEY_DOMAIN + scope.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF


class InstanceLease(Protocol):
    """A held instance lease. Held for the life of the process until `release`."""

    def is_held(self) -> bool:
        """True while the lease is still this process's; False when lost or unverifiable."""
        ...

    def release(self) -> None:
        """Give the lease up (idempotent, best effort, never raises)."""
        ...


class RuntimeStatePort(Protocol):
    """The one storage port for state that must survive a restart. Synchronous by design:
    the runtime wraps it in `asyncio.to_thread` (phase 24 item G4-040 stays open)."""

    def record(self, record: RuntimeRecord) -> None:
        """Store a record. Replaying the same record is a no-op.

        Raises:
            RuntimeRecordConflict: the id exists with different content.
        """
        ...

    def last_close_by_pair(self, epoch_id: str) -> Mapping[tuple[str, str], datetime]:
        """The latest processed bar close per (symbol, interval) of the epoch."""
        ...

    def latest_runtime_marker(self, epoch_id: str) -> RuntimeRecord | None:
        """The last RUNTIME_START or RUNTIME_STOP of the epoch, with its time."""
        ...

    def records(
        self, epoch_id: str, event_types: Collection[RuntimeEventType] | None = None
    ) -> Sequence[RuntimeRecord]:
        """The epoch's records (optionally of the given types) in `record_sort_key` order."""
        ...

    def latest_epoch_pins(self) -> Sequence[RuntimeRecord]:
        """Every EPOCH_PINNED record at the latest pin time across ALL epochs; normally one.

        Cross-epoch on purpose (plan 16-52, REV-18: a new pin starts a new trial): a restart asks
        which pin is in force, whatever epoch it belongs to. No pin gives an empty sequence; the
        records are in `record_sort_key` order.
        """
        ...

    def acquire_instance_lease(self, scope: str) -> InstanceLease | None:
        """Take the instance lease of `scope` for this process, or None when another holds it.

        Never waits: a held lease is a refusal of the start (plan 16-55, B1-WR-07). The lease
        ends with `release` or with the process (PostgreSQL: with the holding session).
        """
        ...


class InMemoryInstanceLease:
    """A lease of the in-memory port: held while its port's registry maps the scope to it."""

    def __init__(self, registry: dict[str, InMemoryInstanceLease], scope: str) -> None:
        self._registry = registry
        self._scope = scope
        self._lost = False

    def is_held(self) -> bool:
        return not self._lost and self._registry.get(self._scope) is self

    def release(self) -> None:
        if self._registry.get(self._scope) is self:
            del self._registry[self._scope]

    def lose(self) -> None:
        """Test seam: the lease disappears, as a session lock does when its connection drops."""
        self._lost = True
        self.release()


class InMemoryRuntimeState:
    """In-memory port: the reference behaviour the PostgreSQL implementation must match.

    One instance models one database, so its lease registry is shared by every `main` call that
    is handed the same instance (two processes on one database).
    """

    def __init__(self) -> None:
        self._by_id: dict[str, RuntimeRecord] = {}
        self._leases: dict[str, InMemoryInstanceLease] = {}

    def record(self, record: RuntimeRecord) -> None:
        event_id = runtime_event_id(record)
        existing = self._by_id.get(event_id)
        if existing is None:
            self._by_id[event_id] = record
            return
        if not same_content(existing, record):
            raise RuntimeRecordConflict(
                f"runtime record {event_id} already exists with different content"
            )

    def last_close_by_pair(self, epoch_id: str) -> Mapping[tuple[str, str], datetime]:
        return last_closes(self.records(epoch_id))

    def latest_runtime_marker(self, epoch_id: str) -> RuntimeRecord | None:
        return latest_marker(self.records(epoch_id))

    def records(
        self, epoch_id: str, event_types: Collection[RuntimeEventType] | None = None
    ) -> Sequence[RuntimeRecord]:
        wanted = None if event_types is None else frozenset(event_types)
        chosen = [
            r
            for r in self._by_id.values()
            if r.epoch_id == epoch_id and (wanted is None or r.event_type in wanted)
        ]
        return sorted(chosen, key=record_sort_key)

    def latest_epoch_pins(self) -> Sequence[RuntimeRecord]:
        pins = [r for r in self._by_id.values() if r.event_type is RuntimeEventType.EPOCH_PINNED]
        if not pins:
            return []
        newest = max(r.occurred_at_utc for r in pins)
        return sorted((r for r in pins if r.occurred_at_utc == newest), key=record_sort_key)

    def acquire_instance_lease(self, scope: str) -> InMemoryInstanceLease | None:
        if scope in self._leases:
            return None
        lease = InMemoryInstanceLease(self._leases, scope)
        self._leases[scope] = lease
        return lease

    def lose_instance_lease(self, scope: str) -> None:
        """Test seam: the holder of `scope` loses its lease without releasing it."""
        lease = self._leases.get(scope)
        if lease is not None:
            lease.lose()


GapKey = tuple[str, str, datetime]


class GapLedger:
    """The in-process set of PAPER_GAP keys already written in this epoch (plan 16-57, B1-WR-05).

    A PAPER_GAP id is keyed on (epoch, symbol, interval, expected close), while the payload names
    the writer (`source`) and its reason. The restart, the supervisor and the pipeline can all
    see the same close; with this ledger the first writer wins and every later writer skips its
    write, so no second payload can end the loop with `RuntimeRecordConflict`. The ledger is
    seeded at start from the gaps the state port already holds and the restart gaps just
    written. `claim` is atomic: the pipeline calls it from its worker thread and the supervisor
    sink from the event-loop thread.
    """

    def __init__(self) -> None:
        self._keys: set[GapKey] = set()
        self._lock = threading.Lock()

    def seed(self, keys: Collection[GapKey]) -> None:
        """Mark gaps written before this point (restored from the store, or by the restart)."""
        with self._lock:
            self._keys.update(keys)

    def claim(self, symbol: str, interval: str, expected_close_utc: datetime) -> bool:
        """True for the first writer of this close (the key is then taken); False afterwards."""
        key = (symbol, interval, expected_close_utc)
        with self._lock:
            if key in self._keys:
                return False
            self._keys.add(key)
            return True


__all__ = [
    "ENTITY_TYPE",
    "EVENT_ID_PREFIX",
    "INSTANCE_LEASE_SCOPE",
    "RUNTIME_ENTITY_ID",
    "GapKey",
    "GapLedger",
    "InMemoryInstanceLease",
    "InMemoryRuntimeState",
    "InstanceLease",
    "RuntimeRecord",
    "RuntimeRecordConflict",
    "RuntimeStatePort",
    "last_closes",
    "latest_marker",
    "record_sort_key",
    "runtime_correlation_id",
    "runtime_correlation_prefix",
    "runtime_entity_id",
    "instance_lease_key",
    "runtime_event_id",
    "same_content",
]
