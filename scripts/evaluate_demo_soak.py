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
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.domain.journal import JournalEvent  # noqa: E402
from src.live.execution_service import EVENT_PLACEMENT_OUTCOME  # noqa: E402

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_INPUT = 2

REGISTRATION_SCHEMA = "demo-soak-registration/1"
REPORT_SCHEMA = "demo-soak-evaluation/1"
MIN_DURATION_DAYS = 21

CRIT_REGISTRATION_HASH = "registration_hash"
CRIT_ORDER_AFTER_REGISTRATION = "order_after_registration"
CRIT_DUPLICATE_ENTRY = "duplicate_entry"

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"

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


def is_order_event(event: JournalEvent) -> bool:
    return event.event_type == EVENT_PLACEMENT_OUTCOME


def is_placed_outcome(event: JournalEvent) -> bool:
    """A placement outcome that was not a refusal; an unreadable payload counts as placed."""
    return (
        event.event_type == EVENT_PLACEMENT_OUTCOME
        and payload_of(event).get("is_no_trade") is not True
    )


def check_registration_hash(*, matches: bool) -> Criterion:
    ok = matches
    return Criterion(
        name=CRIT_REGISTRATION_HASH,
        status=STATUS_PASS if ok else STATUS_FAIL,
        count=0 if ok else 1,
        note="registration SHA-256 equals the committed hash"
        if ok
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


def check_duplicate_entry(events: Sequence[JournalEvent]) -> Criterion:
    by_plan: dict[str, list[JournalEvent]] = {}
    for event in events:
        if is_placed_outcome(event):
            key = event.trade_plan_id or event.approval_id or event.entity_id
            by_plan.setdefault(key, []).append(event)
    offending = {key: rows for key, rows in by_plan.items() if len(rows) > 1}
    ids = sorted({row.journal_event_id for rows in offending.values() for row in rows})
    return _verdict(
        ids,
        len(offending),
        "plans with more than one non-refused placement outcome",
        CRIT_DUPLICATE_ENTRY,
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
) -> Evaluation:
    criteria = (
        check_registration_hash(matches=hash_matches),
        check_order_after_registration(events, committed_at),
        check_duplicate_entry(events),
    )
    window = {
        "first_event_utc": events[0].occurred_at_utc.isoformat(),
        "last_event_utc": events[-1].occurred_at_utc.isoformat(),
        "registered_duration_days": registration.duration_days,
    }
    return Evaluation(criteria=criteria, window=window)


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
    evaluation = evaluate_journal(
        events, registration=registration, hash_matches=matches, committed_at=committed_at
    )
    manifest = {
        "registration": _manifest_entry(args.registration, raw_reg),
        "hash_file": _manifest_entry(args.hash_file, raw_hash),
        "journal": _manifest_entry(args.journal, raw_journal),
    }
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
