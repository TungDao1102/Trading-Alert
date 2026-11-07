"""Judge the live Demo soak from the journal (plan 25-07, criterion 3, D-09).

    python scripts/evaluate_demo_soak.py verify-registration --registration R --hash-file H
    python scripts/evaluate_demo_soak.py evaluate --registration R --hash-file H
        --registration-committed-at T --journal J.jsonl [--annotations A.md] --out REPORT.json

Deviation from D-10 (research Pitfall 2): the Phase 16 soak tools evaluate paper-runtime epochs,
freeze ticks and parity; they cannot judge the live process. This evaluator is new and
journal-based. Only the pattern of the manifest and the SHA-256 is reused. Nothing here reads a
clock except the injected `clock` of `main`, touches the network or changes a threshold: every
number comes from the registration.

Registration (`demo-soak-registration/1`): a markdown file with exactly ONE fenced json block
holding exactly these keys: schema, duration_days (integer, at least 21), symbols (non-empty list
of non-empty strings), trade_generation ({"owner_round_trips_per_week": integer >= 0 or null}),
healthy ({"allowed_degraded_checks": list of check names}), account, host, restart_policy,
restart_rule (non-empty strings), pass_criteria (non-empty list of non-empty strings),
image_commit (40 lowercase hex), registered_at_utc (ISO 8601, timezone aware). Its SHA-256 over the
file bytes is committed (`--hash-file`: the 64 hex characters first on the first line, a
`sha256sum` line is fine) BEFORE the first soak order; `--registration-committed-at` is the commit
time of that hash (`git log -1 --format=%cI -- <hash file>`).

Annotations (`--annotations`, optional): a markdown file with exactly ONE fenced json block holding
a list of {"journal_event_id", "kind": "explained" | "defect", "note" (non-empty), "fixed_at_utc"
(defect only: timezone aware, not before the annotated row)}. An unknown id, a repeated id, another
kind, a missing or extra key is refused (exit 2).

Window and restart rule: window_start is the first journal row, moved to the latest `fixed_at_utc`
of a defect annotation; window_end is the last journal row; the effective window must last at least
duration_days. A defect annotation names the row that showed the defect: that row leaves the
divergence, stop, duplicate, alert and health criteria (it is the cause of the restart). An
`explained` annotation clears only a divergence, alert or health row; it never excuses a position
without a stop or a duplicate entry. A row of any other cause stays unexplained wherever it lies.

Rows each criterion reads (names are imported from the producing module, never re-typed; payload
keys are the producer's own):

  order_after_registration  LIVE_PLACEMENT_OUTCOME   src.live.execution_service
                            the first outcome row must be later than the registration commit
  duplicate_entry           LIVE_PLACEMENT_OUTCOME   payload is_no_trade (False = placed; an
                            unreadable payload counts as placed); the plan is the trade_plan_id
                            column. More than one placed outcome per plan fails.
                            RECONCILE_TICK           src.reconcile.loop; payload counts[kind] with
                            kind DOUBLED_POSITION or DUPLICATE_EXCHANGE_ID fails.
  reconcile_divergence      RECONCILE_TICK           payload divergence_count (a count that cannot
                            be read counts as a divergence); SAFE_MODE_ENTER (src.reconcile.
                            safe_mode journals the literal; a test pins it) fails unannotated.
  position_without_stop     RECONCILE_TICK           payload counts[kind] with kind
                            POSITION_WITHOUT_STOP, ENTRY_WITHOUT_PROTECTIVE or TP_ONLY_POSITION;
                            PROTECTION_CLOSE_REQUIRED (src.execution.protection) payload branch
                            in the stop branches B2, B3, B4_FILL_AFTER_STOP, B5,
                            NO_POSITION_ON_STOP_BUT_EXPOSED, B4_STOP_LOST_UNRESOLVED;
                            PROTECTION_TRANSITION payload to/reason: into CLOSE_REQUIRED with one
                            of those branches, or into UNPROTECTED with reason STOP_LOST or
                            STOP_LOST_AFTER_PROTECTED. A close that kept a good stop (B1) and the
                            normal first-fill step into UNPROTECTED are not counted.
  alerts_explained          OPERATIONAL_ALERT        src.ops.alerts; every row needs an annotation.
  health_explained          HEALTH_VERDICT           src.live.health; payload failing (non-empty) or
                            degraded naming a check outside healthy.allowed_degraded_checks needs
                            an annotation; a verdict without the two lists counts as unhealthy.
  round_trips               PROTECTION_TRANSITION    payload reason FIRST_FILL_STREAM/REST (the
                            entry fill) then a later transition to FLAT, per payload
                            trade_plan_id. Each FULL week of the effective window must hold at least
                            owner_round_trips_per_week completed round trips; null skips it.

Exit codes: 0 PASS; 1 at least one criterion FAILS (`verify-registration`: the file is not a valid
registration or does not match its hash); 2 the input is unusable (a file that is missing or
malformed, an output path that exists). Messages name the file, line or key, never a value that
could be a secret.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.domain.journal import JournalEvent  # noqa: E402
from src.execution.protection import (  # noqa: E402
    BRANCH_B2_STOP_UNCONFIRMED,
    BRANCH_B3_BOTH_AMBIGUOUS,
    BRANCH_B4_FILL_AFTER_STOP,
    BRANCH_B4_STOP_LOST_UNRESOLVED,
    BRANCH_B5_STOP_REJECTED,
    BRANCH_NO_POSITION_BUT_EXPOSED,
    DIVERGENCE_KIND_DOUBLED_POSITION,
    DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE,
    DIVERGENCE_KIND_POSITION_WITHOUT_STOP,
    DIVERGENCE_KIND_TP_ONLY_POSITION,
    EVENT_CLOSE_REQUIRED,
    EVENT_PROTECTION_TRANSITION,
    REASON_FIRST_FILL_REST,
    REASON_FIRST_FILL_STREAM,
    ProtectionState,
)
from src.execution.protection_replay import (  # noqa: E402
    REASON_STOP_LOST,
    REASON_STOP_LOST_AFTER_PROTECTED,
)
from src.live.execution_service import EVENT_PLACEMENT_OUTCOME  # noqa: E402
from src.live.health import VERDICT_EVENT_TYPE  # noqa: E402
from src.ops.alerts import EVENT_OPERATIONAL_ALERT  # noqa: E402
from src.reconcile.compare import DIVERGENCE_KIND_DUPLICATE_EXCHANGE_ID  # noqa: E402
from src.reconcile.loop import RECONCILE_TICK  # noqa: E402

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_INPUT = 2

REGISTRATION_SCHEMA = "demo-soak-registration/1"
REPORT_SCHEMA = "demo-soak-evaluation/1"
MIN_DURATION_DAYS = 21

#: The one event whose producer journals a literal, not a constant (`SafeModeController.
#: enter_safe_mode`); `tests/test_evaluate_demo_soak.py` pins it against the real controller.
EVENT_SAFE_MODE_ENTER = "SAFE_MODE_ENTER"

# Payload keys, as the producers write them.
KEY_IS_NO_TRADE = "is_no_trade"
KEY_DIVERGENCE_COUNT = "divergence_count"
KEY_COUNTS = "counts"
KEY_BRANCH = "branch"
KEY_REASON = "reason"
KEY_TO = "to"
KEY_TRADE_PLAN_ID = "trade_plan_id"
KEY_HEALTH_DEGRADED = "degraded"
KEY_HEALTH_FAILING = "failing"

#: Reconcile divergence kinds that mean a position (or an entry) has no confirmed exchange stop.
#: TP_ONLY_POSITION (a take-profit with no stop) is added to the two the plan named.
STOP_DIVERGENCE_KINDS = frozenset(
    {
        DIVERGENCE_KIND_POSITION_WITHOUT_STOP,
        DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE,
        DIVERGENCE_KIND_TP_ONLY_POSITION,
    }
)
DUPLICATE_DIVERGENCE_KINDS = frozenset(
    {DIVERGENCE_KIND_DOUBLED_POSITION, DIVERGENCE_KIND_DUPLICATE_EXCHANGE_ID}
)
#: The close branches that are about a stop that was rejected, unconfirmed, lost or never there.
#: B1 (a good stop kept, the entry cancel was slow), the operator close and B6 (liquidation price)
#: are not about a missing stop and are not listed.
STOP_BRANCHES = frozenset(
    {
        BRANCH_B2_STOP_UNCONFIRMED,
        BRANCH_B3_BOTH_AMBIGUOUS,
        BRANCH_B4_FILL_AFTER_STOP,
        BRANCH_B5_STOP_REJECTED,
        BRANCH_NO_POSITION_BUT_EXPOSED,
        BRANCH_B4_STOP_LOST_UNRESOLVED,
    }
)
STOP_LOST_REASONS = frozenset({REASON_STOP_LOST, REASON_STOP_LOST_AFTER_PROTECTED})
FIRST_FILL_REASONS = frozenset({REASON_FIRST_FILL_STREAM, REASON_FIRST_FILL_REST})

KIND_EXPLAINED = "explained"
KIND_DEFECT = "defect"

CRIT_REGISTRATION_HASH = "registration_hash"
CRIT_ORDER_AFTER_REGISTRATION = "order_after_registration"
CRIT_DURATION = "duration"
CRIT_DIVERGENCE = "reconcile_divergence"
CRIT_POSITION_WITHOUT_STOP = "position_without_stop"
CRIT_DUPLICATE_ENTRY = "duplicate_entry"
CRIT_ALERTS_EXPLAINED = "alerts_explained"
CRIT_HEALTH_EXPLAINED = "health_explained"
CRIT_ROUND_TRIPS = "round_trips"

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_SKIPPED = "SKIPPED"

_WEEK = timedelta(days=7)
_SECONDS_PER_DAY = Decimal(86400)

_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_JSON_BLOCK = re.compile(r"^```json[ \t]*\r?\n(.*?)^```[ \t]*\r?$", re.MULTILINE | re.DOTALL)

_REGISTRATION_KEYS = frozenset(
    {
        "schema",
        "duration_days",
        "symbols",
        "trade_generation",
        "healthy",
        "account",
        "host",
        "restart_policy",
        "pass_criteria",
        "restart_rule",
        "image_commit",
        "registered_at_utc",
    }
)


class InputError(Exception):
    """A file or flag the evaluator cannot use (exit 2, or exit 1 for verify-registration)."""


# --------------------------------------------------------------------------- #
# Time and file helpers.
# --------------------------------------------------------------------------- #


def _utc_now() -> datetime:
    return datetime.now(UTC)


def parse_utc(value: object, name: str) -> datetime:
    """An ISO 8601 timestamp that carries a timezone, converted to UTC."""
    if not isinstance(value, str) or not value:
        raise InputError(f"{name} must be an ISO 8601 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise InputError(f"{name} must be an ISO 8601 UTC timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InputError(f"{name} must carry a timezone (use a trailing Z)")
    return parsed.astimezone(UTC)


def _read_bytes(path: Path, name: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        raise InputError(f"{name} cannot be read") from None


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_blocks(raw: bytes, name: str) -> list[str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise InputError(f"{name} is not UTF-8 text") from None
    return [match.group(1) for match in _JSON_BLOCK.finditer(text)]


# --------------------------------------------------------------------------- #
# The registration.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Registration:
    """The pre-registered soak, parsed from the fenced json block of the registration file."""

    duration_days: int
    symbols: tuple[str, ...]
    owner_round_trips_per_week: int | None
    allowed_degraded_checks: frozenset[str]
    account: str
    host: str
    restart_policy: str
    pass_criteria: tuple[str, ...]
    restart_rule: str
    image_commit: str
    registered_at_utc: datetime


def _require_text(document: dict[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"registration field {key} must be a non-empty string")
    return value


def _require_text_list(value: object, key: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        raise InputError(f"registration field {key} must be a non-empty list of non-empty strings")
    return tuple(value)


def parse_registration(raw: bytes) -> Registration:
    """Validate the registration file bytes; every refusal names the field."""
    blocks = _json_blocks(raw, "registration")
    if len(blocks) != 1:
        raise InputError(f"registration must hold exactly one json block, found {len(blocks)}")
    try:
        document = json.loads(blocks[0])
    except ValueError:
        raise InputError("registration json block is not valid JSON") from None
    if not isinstance(document, dict):
        raise InputError("registration json block must be an object")
    unknown = sorted(set(document) - _REGISTRATION_KEYS)
    if unknown:
        raise InputError(f"registration has an unknown field: {unknown[0]}")
    missing = sorted(_REGISTRATION_KEYS - set(document))
    if missing:
        raise InputError(f"registration is missing the field {missing[0]}")
    if document["schema"] != REGISTRATION_SCHEMA:
        raise InputError(f"registration schema must be {REGISTRATION_SCHEMA}")
    days = document["duration_days"]
    if isinstance(days, bool) or not isinstance(days, int):
        raise InputError("registration field duration_days must be an integer")
    if days < MIN_DURATION_DAYS:
        raise InputError(f"registration field duration_days must be at least {MIN_DURATION_DAYS}")
    symbols = _require_text_list(document["symbols"], "symbols")
    generation = document["trade_generation"]
    if not isinstance(generation, dict) or "owner_round_trips_per_week" not in generation:
        raise InputError("registration field trade_generation needs owner_round_trips_per_week")
    trips = generation["owner_round_trips_per_week"]
    if trips is not None and (isinstance(trips, bool) or not isinstance(trips, int) or trips < 0):
        raise InputError("registration field owner_round_trips_per_week must be an integer or null")
    healthy = document["healthy"]
    allowed = healthy.get("allowed_degraded_checks") if isinstance(healthy, dict) else None
    if not isinstance(allowed, list) or not all(isinstance(item, str) and item for item in allowed):
        raise InputError("registration field allowed_degraded_checks must be a list of names")
    commit = document["image_commit"]
    if not isinstance(commit, str) or not _COMMIT.fullmatch(commit):
        raise InputError("registration field image_commit must be 40 lowercase hex characters")
    return Registration(
        duration_days=days,
        symbols=symbols,
        owner_round_trips_per_week=trips,
        allowed_degraded_checks=frozenset(allowed),
        account=_require_text(document, "account"),
        host=_require_text(document, "host"),
        restart_policy=_require_text(document, "restart_policy"),
        pass_criteria=_require_text_list(document["pass_criteria"], "pass_criteria"),
        restart_rule=_require_text(document, "restart_rule"),
        image_commit=commit,
        registered_at_utc=parse_utc(document["registered_at_utc"], "registered_at_utc"),
    )


def read_recorded_hash(raw: bytes) -> str:
    """The recorded SHA-256 (lowercase hex): the first token of the hash file."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise InputError("hash file is not UTF-8 text") from None
    tokens = text.split()
    if not tokens or not _HEX64.fullmatch(tokens[0]):
        raise InputError("hash file must start with a 64-character SHA-256 hex string")
    return tokens[0].lower()


# --------------------------------------------------------------------------- #
# The journal file (JSONL, one JournalEvent per line).
# --------------------------------------------------------------------------- #

_EVENT_FIELDS = (
    "journal_event_id",
    "occurred_at_utc",
    "event_type",
    "entity_type",
    "entity_id",
    "correlation_id",
    "signal_id",
    "trade_plan_id",
    "approval_id",
    "order_id",
    "position_id",
    "payload_json",
    "created_at_utc",
)
_EVENT_OPTIONAL = frozenset(
    {
        "signal_id",
        "trade_plan_id",
        "approval_id",
        "order_id",
        "position_id",
        "payload_json",
        "created_at_utc",
    }
)


def event_to_jsonl(event: JournalEvent) -> bytes:
    """One journal row as a JSONL line (sorted keys, LF); the inverse of `event_from_line`."""
    document: dict[str, Any] = {}
    for name in _EVENT_FIELDS:
        value = getattr(event, name)
        document[name] = value.isoformat() if isinstance(value, datetime) else value
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def event_from_line(line: str, number: int) -> JournalEvent:
    where = f"journal line {number}"
    try:
        document = json.loads(line)
    except ValueError:
        raise InputError(f"{where} is not valid JSON") from None
    if not isinstance(document, dict) or set(document) - set(_EVENT_FIELDS):
        raise InputError(f"{where} is not a journal row")
    if (set(_EVENT_FIELDS) - _EVENT_OPTIONAL) - set(document):
        raise InputError(f"{where} lacks a required field")
    values: dict[str, Any] = dict(document)
    for key in ("occurred_at_utc", "created_at_utc"):
        if values.get(key) is not None:
            values[key] = parse_utc(values[key], f"{where} {key}")
    try:
        return JournalEvent(**values)
    except (TypeError, ValueError) as exc:
        raise InputError(f"{where} is not a valid journal event ({type(exc).__name__})") from None


def parse_journal(raw: bytes) -> list[JournalEvent]:
    """Every event of a JSONL journal, ordered by occurred_at_utc then journal_event_id."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise InputError("journal is not UTF-8 text") from None
    events: list[JournalEvent] = []
    seen: set[str] = set()
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        event = event_from_line(line, number)
        if event.journal_event_id in seen:
            raise InputError(f"journal line {number} repeats a journal_event_id")
        seen.add(event.journal_event_id)
        events.append(event)
    if not events:
        raise InputError("journal holds no events")
    events.sort(key=lambda e: (e.occurred_at_utc, e.journal_event_id))
    return events


def payload_of(event: JournalEvent) -> dict[str, Any]:
    """The payload object of an event; anything that is not a JSON object reads as empty."""
    if not event.payload_json:
        return {}
    try:
        document = json.loads(event.payload_json)
    except ValueError:
        return {}
    return document if isinstance(document, dict) else {}


# --------------------------------------------------------------------------- #
# The criteria: pure functions over the event list.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Criterion:
    name: str
    status: str
    count: int
    ids: tuple[str, ...] = ()
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "count": self.count,
            "ids": list(self.ids),
            "note": self.note,
        }


def _verdict(offending: Sequence[str], count: int, note: str, name: str) -> Criterion:
    return Criterion(
        name=name,
        status=STATUS_FAIL if count else STATUS_PASS,
        count=count,
        ids=tuple(offending),
        note=note,
    )


# ---- annotations ---------------------------------------------------------- #


@dataclass(frozen=True)
class Annotation:
    """One owner annotation of a journal row: explained, or a defect fixed at `fixed_at`."""

    journal_event_id: str
    kind: str
    note: str
    fixed_at: datetime | None


_ANNOTATION_KEYS = frozenset({"journal_event_id", "kind", "note", "fixed_at_utc"})


def parse_annotations(raw: bytes, events: Sequence[JournalEvent]) -> dict[str, Annotation]:
    """Validate the annotations file against the journal; every refusal names the entry."""
    blocks = _json_blocks(raw, "annotations")
    if len(blocks) != 1:
        raise InputError(f"annotations must hold exactly one json block, found {len(blocks)}")
    try:
        document = json.loads(blocks[0])
    except ValueError:
        raise InputError("annotations json block is not valid JSON") from None
    if not isinstance(document, list):
        raise InputError("annotations json block must be a list")
    occurred = {e.journal_event_id: e.occurred_at_utc for e in events}
    found: dict[str, Annotation] = {}
    for number, item in enumerate(document, start=1):
        where = f"annotation {number}"
        if not isinstance(item, dict) or set(item) - _ANNOTATION_KEYS:
            raise InputError(f"{where} must be an object with the documented keys only")
        event_id = item.get("journal_event_id")
        if not isinstance(event_id, str) or event_id not in occurred:
            raise InputError(f"{where} names a journal_event_id that is not in the journal")
        if event_id in found:
            raise InputError(f"{where} repeats a journal_event_id")
        kind = item.get("kind")
        if kind not in (KIND_EXPLAINED, KIND_DEFECT):
            raise InputError(f"{where} kind must be {KIND_EXPLAINED} or {KIND_DEFECT}")
        note = item.get("note")
        if not isinstance(note, str) or not note.strip():
            raise InputError(f"{where} needs a non-empty note")
        fixed_at: datetime | None = None
        if kind == KIND_EXPLAINED:
            if "fixed_at_utc" in item:
                raise InputError(f"{where} is explained and must not carry fixed_at_utc")
        else:
            if "fixed_at_utc" not in item:
                raise InputError(f"{where} is a defect and needs fixed_at_utc")
            fixed_at = parse_utc(item["fixed_at_utc"], f"{where} fixed_at_utc")
            if fixed_at < occurred[event_id]:
                raise InputError(f"{where} fixed_at_utc is before the annotated row")
        found[event_id] = Annotation(event_id, kind, note, fixed_at)
    return found


def _is_defect_cause(event: JournalEvent, annotations: Mapping[str, Annotation]) -> bool:
    found = annotations.get(event.journal_event_id)
    return found is not None and found.kind == KIND_DEFECT


# ---- payload readers ------------------------------------------------------ #


def _text(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _tick_divergence_count(event: JournalEvent) -> int | None:
    """The divergence count of a reconcile tick row; None when it cannot be read."""
    count = payload_of(event).get(KEY_DIVERGENCE_COUNT)
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        return None
    return count


def _tick_kind_count(event: JournalEvent, kinds: frozenset[str]) -> int:
    counts = payload_of(event).get(KEY_COUNTS)
    if not isinstance(counts, dict):
        return 0
    total = 0
    for kind in kinds:
        value = counts.get(kind)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            total += value
    return total


def is_order_event(event: JournalEvent) -> bool:
    return event.event_type == EVENT_PLACEMENT_OUTCOME


def is_placed_outcome(event: JournalEvent) -> bool:
    """A placement outcome that was not a refusal; an unreadable payload counts as placed."""
    return is_order_event(event) and payload_of(event).get(KEY_IS_NO_TRADE) is not True


def _plan_of(event: JournalEvent) -> str:
    return _text(payload_of(event), KEY_TRADE_PLAN_ID) or event.trade_plan_id or event.entity_id


# ---- the criteria --------------------------------------------------------- #


def check_registration_hash(*, matches: bool) -> Criterion:
    return Criterion(
        name=CRIT_REGISTRATION_HASH,
        status=STATUS_PASS if matches else STATUS_FAIL,
        count=0 if matches else 1,
        note="registration SHA-256 equals the committed hash"
        if matches
        else "registration SHA-256 differs from the committed hash",
    )


def check_order_after_registration(
    events: Sequence[JournalEvent], committed_at: datetime
) -> Criterion:
    orders = [e for e in events if is_order_event(e)]
    if not orders:
        return Criterion(
            name=CRIT_ORDER_AFTER_REGISTRATION,
            status=STATUS_PASS,
            count=0,
            note="no order event in the journal",
        )
    first = min(orders, key=lambda e: (e.occurred_at_utc, e.journal_event_id))
    if first.occurred_at_utc > committed_at:
        return Criterion(
            name=CRIT_ORDER_AFTER_REGISTRATION,
            status=STATUS_PASS,
            count=0,
            note="the first order event follows the registration commit",
        )
    return Criterion(
        name=CRIT_ORDER_AFTER_REGISTRATION,
        status=STATUS_FAIL,
        count=1,
        ids=(first.journal_event_id,),
        note="order before registration: the first order event is not later than the commit",
    )


@dataclass(frozen=True)
class Window:
    """The effective soak window after the restart rule."""

    start: datetime
    end: datetime
    effective_days: Decimal
    defect_count: int


def compute_window(events: Sequence[JournalEvent], annotations: Mapping[str, Annotation]) -> Window:
    """First row (moved to the latest defect fix) to the last row; `events` are sorted."""
    start = events[0].occurred_at_utc
    fixes = [a.fixed_at for a in annotations.values() if a.fixed_at is not None]
    if fixes:
        start = max(start, max(fixes))
    end = events[-1].occurred_at_utc
    delta = max(end - start, timedelta(0))
    seconds = (
        Decimal(delta.days) * _SECONDS_PER_DAY
        + Decimal(delta.seconds)
        + Decimal(delta.microseconds) / Decimal(1_000_000)
    )
    return Window(start, end, seconds / _SECONDS_PER_DAY, len(fixes))


def check_duration(window: Window, registration: Registration) -> Criterion:
    ok = window.effective_days >= Decimal(registration.duration_days)
    return Criterion(
        name=CRIT_DURATION,
        status=STATUS_PASS if ok else STATUS_FAIL,
        count=0 if ok else 1,
        note=(
            f"effective window {window.effective_days:.4f} days of "
            f"{registration.duration_days} registered"
        ),
    )


def check_divergence(
    events: Sequence[JournalEvent], annotations: Mapping[str, Annotation]
) -> Criterion:
    offending: list[str] = []
    for event in events:
        if event.event_type == RECONCILE_TICK:
            count = _tick_divergence_count(event)
            needs = count is None or count > 0
        else:
            needs = event.event_type == EVENT_SAFE_MODE_ENTER
        if needs and event.journal_event_id not in annotations:
            offending.append(event.journal_event_id)
    return _verdict(
        offending,
        len(offending),
        "reconcile ticks with a divergence and SAFE_MODE entries need an owner annotation",
        CRIT_DIVERGENCE,
    )


def _is_stop_row(event: JournalEvent) -> bool:
    payload = payload_of(event)
    if event.event_type == RECONCILE_TICK:
        return _tick_kind_count(event, STOP_DIVERGENCE_KINDS) > 0
    if event.event_type == EVENT_CLOSE_REQUIRED:
        return _text(payload, KEY_BRANCH) in STOP_BRANCHES
    if event.event_type == EVENT_PROTECTION_TRANSITION:
        target = _text(payload, KEY_TO)
        reason = _text(payload, KEY_REASON)
        if target == ProtectionState.CLOSE_REQUIRED.value:
            return reason in STOP_BRANCHES
        if target == ProtectionState.UNPROTECTED.value:
            return reason in STOP_LOST_REASONS
    return False


def check_position_without_stop(
    events: Sequence[JournalEvent], annotations: Mapping[str, Annotation]
) -> Criterion:
    """An `explained` annotation never excuses these rows; only a defect annotation removes one."""
    offending = [
        e.journal_event_id
        for e in events
        if _is_stop_row(e) and not _is_defect_cause(e, annotations)
    ]
    return _verdict(
        offending,
        len(offending),
        "rows showing a position or entry without a confirmed exchange-side stop",
        CRIT_POSITION_WITHOUT_STOP,
    )


def check_duplicate_entry(
    events: Sequence[JournalEvent], annotations: Mapping[str, Annotation]
) -> Criterion:
    """An `explained` annotation never excuses a duplicate; a defect annotation removes its row."""
    by_plan: dict[str, list[JournalEvent]] = {}
    for event in events:
        if is_placed_outcome(event):
            key = event.trade_plan_id or event.approval_id or event.entity_id
            by_plan.setdefault(key, []).append(event)
    ids: set[str] = set()
    count = 0
    for rows in by_plan.values():
        if len(rows) > 1 and not any(_is_defect_cause(row, annotations) for row in rows):
            count += 1
            ids.update(row.journal_event_id for row in rows)
    for event in events:
        if (
            event.event_type == RECONCILE_TICK
            and _tick_kind_count(event, DUPLICATE_DIVERGENCE_KINDS) > 0
            and not _is_defect_cause(event, annotations)
        ):
            count += 1
            ids.add(event.journal_event_id)
    return _verdict(
        sorted(ids),
        count,
        "plans with more than one non-refused placement outcome, doubled positions and "
        "duplicate exchange ids",
        CRIT_DUPLICATE_ENTRY,
    )


def check_alerts_explained(
    events: Sequence[JournalEvent], annotations: Mapping[str, Annotation]
) -> Criterion:
    offending = [
        e.journal_event_id
        for e in events
        if e.event_type == EVENT_OPERATIONAL_ALERT and e.journal_event_id not in annotations
    ]
    return _verdict(
        offending,
        len(offending),
        "every OPERATIONAL_ALERT row needs an owner annotation",
        CRIT_ALERTS_EXPLAINED,
    )


def _verdict_is_unhealthy(event: JournalEvent, allowed: frozenset[str]) -> bool:
    payload = payload_of(event)
    degraded = payload.get(KEY_HEALTH_DEGRADED)
    failing = payload.get(KEY_HEALTH_FAILING)
    if not isinstance(degraded, list) or not isinstance(failing, list):
        return True
    if failing:
        return True
    return any(not isinstance(name, str) or name not in allowed for name in degraded)


def check_health_explained(
    events: Sequence[JournalEvent],
    annotations: Mapping[str, Annotation],
    registration: Registration,
) -> Criterion:
    offending = [
        e.journal_event_id
        for e in events
        if e.event_type == VERDICT_EVENT_TYPE
        and _verdict_is_unhealthy(e, registration.allowed_degraded_checks)
        and e.journal_event_id not in annotations
    ]
    return _verdict(
        offending,
        len(offending),
        "unhealthy HEALTH_VERDICT rows need an owner annotation",
        CRIT_HEALTH_EXPLAINED,
    )


def check_round_trips(
    events: Sequence[JournalEvent], window: Window, registration: Registration
) -> Criterion:
    required = registration.owner_round_trips_per_week
    if required is None:
        return Criterion(
            name=CRIT_ROUND_TRIPS,
            status=STATUS_SKIPPED,
            count=0,
            note="owner_round_trips_per_week is null in the registration: criterion skipped",
        )
    filled: set[str] = set()
    completed_at: dict[str, datetime] = {}
    for event in events:
        if event.event_type != EVENT_PROTECTION_TRANSITION:
            continue
        payload = payload_of(event)
        plan = _plan_of(event)
        if _text(payload, KEY_REASON) in FIRST_FILL_REASONS:
            filled.add(plan)
        elif (
            _text(payload, KEY_TO) == ProtectionState.FLAT.value
            and plan in filled
            and plan not in completed_at
        ):
            completed_at[plan] = event.occurred_at_utc
    full_weeks = int(window.effective_days // 7)
    per_week = [0] * full_weeks
    for moment in completed_at.values():
        index = (moment - window.start) // _WEEK
        if 0 <= index < full_weeks:
            per_week[index] += 1
    short = [(i + 1, got) for i, got in enumerate(per_week) if got < required]
    detail = "; ".join(f"week {number}: {got} of {required}" for number, got in short)
    return Criterion(
        name=CRIT_ROUND_TRIPS,
        status=STATUS_FAIL if short else STATUS_PASS,
        count=len(short),
        note=(
            f"weeks short of the registered round trips: {detail}"
            if short
            else f"{full_weeks} full weeks, at least {required} completed round trips each"
        ),
    )


# --------------------------------------------------------------------------- #
# The evaluation and the report.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Evaluation:
    criteria: tuple[Criterion, ...]
    window: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(c.status != STATUS_FAIL for c in self.criteria)


def evaluate_journal(
    events: Sequence[JournalEvent],
    *,
    registration: Registration,
    hash_matches: bool,
    committed_at: datetime,
    annotations: Mapping[str, Annotation] | None = None,
) -> Evaluation:
    """Every criterion over the sorted events; overall PASS only when none FAILS."""
    notes: Mapping[str, Annotation] = annotations or {}
    window = compute_window(events, notes)
    criteria = (
        check_registration_hash(matches=hash_matches),
        check_order_after_registration(events, committed_at),
        check_duration(window, registration),
        check_divergence(events, notes),
        check_position_without_stop(events, notes),
        check_duplicate_entry(events, notes),
        check_alerts_explained(events, notes),
        check_health_explained(events, notes, registration),
        check_round_trips(events, window, registration),
    )
    report_window = {
        "first_event_utc": events[0].occurred_at_utc.isoformat(),
        "last_event_utc": events[-1].occurred_at_utc.isoformat(),
        "window_start_utc": window.start.isoformat(),
        "window_end_utc": window.end.isoformat(),
        "effective_days": f"{window.effective_days:.4f}",
        "registered_duration_days": registration.duration_days,
        "defect_count": window.defect_count,
    }
    return Evaluation(criteria=criteria, window=report_window)


def _manifest_entry(path: Path, raw: bytes) -> dict[str, Any]:
    return {"file": path.name, "bytes": len(raw), "sha256": _sha256(raw)}


def render_report(
    evaluation: Evaluation, *, manifest: dict[str, Any], now: datetime, committed_at: datetime
) -> str:
    document = {
        "schema": REPORT_SCHEMA,
        "verdict": STATUS_PASS if evaluation.passed else STATUS_FAIL,
        "evaluated_at_utc": now.isoformat(),
        "registration_committed_at_utc": committed_at.isoformat(),
        "criteria": [c.as_dict() for c in evaluation.criteria],
        "window": evaluation.window,
        "manifest": manifest,
    }
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def write_create_only(path: Path, text: str) -> None:
    """Write `text` (LF) to a NEW file; an existing path is refused."""
    try:
        with path.open("xb") as handle:
            handle.write(text.encode("utf-8"))
    except FileExistsError:
        raise InputError("the output file already exists; refusing to overwrite it") from None
    except OSError:
        raise InputError("the output file cannot be written") from None


# --------------------------------------------------------------------------- #
# The subcommands.
# --------------------------------------------------------------------------- #


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    commands = parser.add_subparsers(dest="command", required=True)

    verify = commands.add_parser(
        "verify-registration", help="check the registration file against its committed hash"
    )
    verify.add_argument("--registration", required=True, type=Path)
    verify.add_argument("--hash-file", required=True, type=Path)

    run = commands.add_parser("evaluate", help="judge an exported journal against the registration")
    run.add_argument("--registration", required=True, type=Path)
    run.add_argument("--hash-file", required=True, type=Path)
    run.add_argument(
        "--registration-committed-at",
        required=True,
        help="commit time of the hash file (ISO 8601, timezone aware)",
    )
    run.add_argument("--journal", required=True, type=Path, help="JSONL journal export")
    run.add_argument("--annotations", type=Path, default=None, help="owner annotations (markdown)")
    run.add_argument("--out", required=True, type=Path, help="report file (create-only)")
    return parser


def _load_registration(
    registration: Path, hash_file: Path
) -> tuple[Registration, bytes, bytes, bool]:
    raw = _read_bytes(registration, "registration")
    raw_hash = _read_bytes(hash_file, "hash file")
    parsed = parse_registration(raw)
    recorded = read_recorded_hash(raw_hash)
    return parsed, raw, raw_hash, recorded == _sha256(raw)


def _cmd_verify(args: argparse.Namespace) -> int:
    try:
        _, _, _, matches = _load_registration(args.registration, args.hash_file)
    except InputError as exc:
        print(f"registration refused: {exc}", file=sys.stderr)
        return EXIT_FAIL
    if not matches:
        print("registration refused: its SHA-256 differs from the committed hash", file=sys.stderr)
        return EXIT_FAIL
    print("registration valid and matches its committed hash")
    return EXIT_PASS


def _cmd_evaluate(args: argparse.Namespace, clock: Callable[[], datetime]) -> int:
    registration, raw_reg, raw_hash, matches = _load_registration(args.registration, args.hash_file)
    committed_at = parse_utc(args.registration_committed_at, "--registration-committed-at")
    raw_journal = _read_bytes(args.journal, "journal")
    events = parse_journal(raw_journal)
    manifest: dict[str, Any] = {
        "registration": _manifest_entry(args.registration, raw_reg),
        "hash_file": _manifest_entry(args.hash_file, raw_hash),
        "journal": _manifest_entry(args.journal, raw_journal),
    }
    annotations: dict[str, Annotation] = {}
    if args.annotations is not None:
        raw_notes = _read_bytes(args.annotations, "annotations")
        annotations = parse_annotations(raw_notes, events)
        manifest["annotations"] = _manifest_entry(args.annotations, raw_notes)
    evaluation = evaluate_journal(
        events,
        registration=registration,
        hash_matches=matches,
        committed_at=committed_at,
        annotations=annotations,
    )
    text = render_report(evaluation, manifest=manifest, now=clock(), committed_at=committed_at)
    write_create_only(args.out, text)
    print(f"verdict {STATUS_PASS if evaluation.passed else STATUS_FAIL}")
    for criterion in evaluation.criteria:
        print(f"  {criterion.name}: {criterion.status} ({criterion.count})")
    return EXIT_PASS if evaluation.passed else EXIT_FAIL


def main(argv: Sequence[str] | None = None, *, clock: Callable[[], datetime] = _utc_now) -> int:
    """Run one subcommand. `clock` is the only time source (it stamps the report)."""
    args = _parser().parse_args(argv)
    try:
        if args.command == "verify-registration":
            return _cmd_verify(args)
        return _cmd_evaluate(args, clock)
    except InputError as exc:
        print(f"cannot evaluate: {exc}", file=sys.stderr)
        return EXIT_INPUT


if __name__ == "__main__":
    raise SystemExit(main())
