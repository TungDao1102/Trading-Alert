"""Offline journal-depth report CLI (Phase 10, plan 10-12, D-01, D-03, D-04, D-05).

The single edge module of the analytics phase: it loads the evidence, decision and universe
files through `src.adapters.analytics_files`, composes the frozen `ReportInputs`, runs the pure
core (`build_journal_depth_report`, `render_markdown`, `sidecar_text`), verifies that the
Markdown and the sidecar agree, and writes exactly two files under the confined reports root.

Contract (UI-SPEC Interaction Contract):

- stdout on success is exactly four lines: `Report: <path>`, `Sidecar: <path>`,
  `Digest: sha256:<64 hex>` and `Kill gate: <STATE>`; exit 0, also for a terminal
  INSUFFICIENT_EDGE (a valid outcome, never an error).
- exit 1: the report could not be produced (nothing is written); exit 2: invalid arguments.
- The wall clock is read at most once, only when `--as-of` is omitted, inside
  `_resolve_as_of`. Every other instant is an injected argument.
- No network, no exchange access, no Telegram send, no float. Error output carries names and
  exception types only, never file contents or credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, NoReturn

from src.adapters.analytics_files import (
    REPORTS_ROOT,
    BacktestEvidence,
    DecisionsFile,
    DecisionsFileError,
    EvidenceFile,
    EvidenceFileError,
    PathConfinementError,
    confine_output_dir,
    load_decisions_file,
    load_evidence_file,
    load_universe_file,
    read_protocol_text,
    scan_family_facts,
)
from src.adapters.analytics_store import (
    LiveRows,
    append_kill_gate_event,
    read_candles,
    read_journal_events,
    read_live_rows,
)
from src.analytics.clock import clock_start_from_protocol
from src.analytics.family import KillGateInputError
from src.analytics.inputs import normalize_backtest
from src.analytics.killgate import (
    KILL_GATE_EVENT_TYPE,
    QUESTION_APPROVED_EVENT_TYPE,
    ResetRecord,
    build_kill_gate_event,
    priors_from_events,
    resets_from_events,
)
from src.analytics.lifecycle import (
    normalize_backtest_lifecycle,
    normalize_live_lifecycle,
    normalize_paper_lifecycle,
)
from src.analytics.live_outcomes import normalize_live_outcomes
from src.analytics.no_trade import no_trade_from_paper
from src.analytics.render import render_markdown, report_file_stem
from src.analytics.render_common import RenderError
from src.analytics.render_sidecar import build_sidecar, sidecar_text, verify_render
from src.analytics.report import (
    LIVE_ORDERS_DISABLED_EVENT,
    LIVE_ORDERS_ENABLED_EVENT,
    EvidenceInputs,
    InputNote,
    JournalDepthReport,
    ReportInputs,
    build_journal_depth_report,
)
from src.analytics.stats import r_value
from src.analytics.types import (
    DEFAULT_BASE_SEED,
    DEFAULT_RESAMPLES,
    MIN_RESAMPLES,
    AnalyticsInputError,
    EvidenceKind,
    OutcomeContext,
    TradeOutcome,
)
from src.backtest.simulator import TradeRecord
from src.core.types import Candle
from src.db.models import make_session_factory, session_scope
from src.domain.enums import KillGateState
from src.domain.journal import JournalEvent
from src.paper.journal import PaperRecord

__all__ = ["CliArgs", "main", "parse_args"]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DECISIONS = _REPO_ROOT / "docs" / "research" / "kill_gate_decisions.json"
_DEFAULT_RAW_ROOT = _REPO_ROOT / "data" / "raw"
_DEFAULT_REPORTS_ROOT = _REPO_ROOT / REPORTS_ROOT
_SHEETS_ROOT = _REPO_ROOT / "docs" / "research" / "families"

_FAILURE_TAIL = (
    "No file was written. Fix the cause and re-run journal-report.ps1 with the same -AsOf."
)

ClockFn = Callable[[], datetime]


class _UsageError(Exception):
    """Invalid command-line arguments (exit code 2)."""


class _RenderVerificationError(Exception):
    """The Markdown and the sidecar disagree; carries fixed-vocabulary problem strings only."""


class _ArgumentParser(argparse.ArgumentParser):
    """argparse with an error handler that raises instead of exiting with a usage dump."""

    def error(self, message: str) -> NoReturn:
        raise _UsageError(message)


@dataclass(frozen=True)
class CliArgs:
    """Parsed command line; `as_of` is None when the clock must be read at the edge."""

    as_of: datetime | None
    out_dir: Path | None
    record: bool
    universe: Path | None
    evidence: Path | None
    decisions: Path
    raw_root: Path
    resamples: int
    seed: int
    no_db: bool
    reports_root: Path


# --------------------------------------------------------------------------- #
# Argument parsing (no clock, no environment)
# --------------------------------------------------------------------------- #


def _parse_as_of(text: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise _UsageError("--as-of must be an ISO-8601 timestamp with a UTC offset") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _UsageError("--as-of must carry a UTC offset (a naive timestamp is refused)")
    return parsed.astimezone(UTC)


def _build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="python -m src.analytics.cli",
        description=(
            "Generate the offline journal-depth and kill-gate report (Markdown plus JSON "
            "sidecar) under the reports root. Read-only unless --record is given."
        ),
        allow_abbrev=False,
    )
    parser.add_argument("--as-of", dest="as_of", help="ISO-8601 timestamp with a UTC offset")
    parser.add_argument("--out-dir", dest="out_dir", type=Path, help="directory under the root")
    parser.add_argument("--record", action="store_true", help="append one KILL_GATE_EVALUATION")
    parser.add_argument("--universe", type=Path, help="research-universe file")
    parser.add_argument("--evidence", type=Path, help="analytics evidence file")
    parser.add_argument("--decisions", type=Path, default=_DEFAULT_DECISIONS)
    parser.add_argument("--raw-root", dest="raw_root", type=Path, default=_DEFAULT_RAW_ROOT)
    parser.add_argument("--resamples", type=int, default=DEFAULT_RESAMPLES)
    parser.add_argument("--seed", type=int, default=DEFAULT_BASE_SEED)
    parser.add_argument("--no-db", dest="no_db", action="store_true", help="never read a database")
    parser.add_argument(
        "--reports-root",
        dest="reports_root",
        type=Path,
        default=_DEFAULT_REPORTS_ROOT,
        help="confinement root for output (test hook; default <repo>/data/reports)",
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> CliArgs:
    """Parse `argv`; raises `_UsageError` (exit 2) on anything invalid."""
    namespace = _build_parser().parse_args(None if argv is None else list(argv))
    if namespace.resamples < MIN_RESAMPLES:
        raise _UsageError(f"--resamples must be an integer >= {MIN_RESAMPLES}")
    return CliArgs(
        as_of=None if namespace.as_of is None else _parse_as_of(namespace.as_of),
        out_dir=namespace.out_dir,
        record=namespace.record,
        universe=namespace.universe,
        evidence=namespace.evidence,
        decisions=namespace.decisions,
        raw_root=namespace.raw_root,
        resamples=namespace.resamples,
        seed=namespace.seed,
        no_db=namespace.no_db,
        reports_root=namespace.reports_root,
    )


def _resolve_as_of(args: CliArgs, now_fn: ClockFn | None) -> datetime:
    """The report instant: `--as-of`, else the one wall-clock read of the whole program."""
    if args.as_of is not None:
        return args.as_of
    moment = now_fn() if now_fn is not None else datetime.now(UTC)
    return moment.astimezone(UTC).replace(microsecond=0)


# --------------------------------------------------------------------------- #
# Input composition (pure functions over the loaded files)
# --------------------------------------------------------------------------- #


def _candles_for(
    outcomes: Sequence[TradeOutcome], raw_root: Path
) -> tuple[dict[str, tuple[Candle, ...]], tuple[InputNote, ...]]:
    """1m candles per symbol covering each outcome window, read from the immutable store."""
    windows: dict[str, tuple[datetime, datetime]] = {}
    for outcome in outcomes:
        if outcome.entry_time_utc is None or outcome.exit_time_utc is None:
            continue
        start, end = windows.get(outcome.symbol, (outcome.entry_time_utc, outcome.exit_time_utc))
        windows[outcome.symbol] = (
            min(start, outcome.entry_time_utc),
            max(end, outcome.exit_time_utc),
        )
    if not raw_root.is_dir():
        return {}, ()  # no store: the core reports NO_1M_COVERAGE; nothing is fabricated
    candles: dict[str, tuple[Candle, ...]] = {}
    notes: list[InputNote] = []
    for symbol in sorted(windows):
        start, end = windows[symbol]
        try:
            result = read_candles(raw_root, symbol, start, end)
        except ValueError:
            raise AnalyticsInputError("a trade symbol is not valid for a candle read") from None
        candles[symbol] = result.candles
        if result.rejected > 0:
            notes.append(InputNote(f"candles:{symbol}", "MALFORMED_ROW", result.rejected))
    return candles, tuple(notes)


def _realized_r_by_signal(outcomes: Sequence[TradeOutcome]) -> dict[str, Decimal]:
    """R multiple per signal for the outcomes that carry a usable risk value."""
    realized: dict[str, Decimal] = {}
    for outcome in outcomes:
        value = r_value(outcome.realized_pnl, outcome.realized_risk)
        if outcome.signal_id is not None and value is not None:
            realized[outcome.signal_id] = value
    return realized


def _backtest_inputs(entries: Sequence[BacktestEvidence], raw_root: Path) -> EvidenceInputs:
    ordered = sorted(entries, key=lambda entry: entry.experiment.experiment_id)
    experiment_ids = [entry.experiment.experiment_id for entry in ordered]
    if len(set(experiment_ids)) != len(experiment_ids):
        raise AnalyticsInputError("duplicate experiment_id across evidence entries")
    trades: list[TradeRecord] = []
    contexts: dict[str, OutcomeContext] = {}
    seen: set[str] = set()
    for entry in ordered:
        for trade in entry.trades:
            if trade.trade_id in seen:
                raise AnalyticsInputError(
                    f"duplicate trade_id {trade.trade_id!r} across experiments"
                )
            seen.add(trade.trade_id)
            trades.append(trade)
        contexts.update(entry.contexts)
    normalized = normalize_backtest(trades, contexts)
    candles, notes = _candles_for(normalized.outcomes, raw_root)
    return EvidenceInputs(
        kind=EvidenceKind.BACKTEST,
        outcomes=normalized.outcomes,
        lifecycle=normalize_backtest_lifecycle(normalized.outcomes),
        no_trades=normalized.rejects,
        candles_by_symbol=candles,
        realized_r_by_signal=_realized_r_by_signal(normalized.outcomes),
        experiments=tuple(entry.experiment for entry in ordered),
        notes=notes,
    )


def _paper_inputs(records: Sequence[PaperRecord]) -> EvidenceInputs:
    return EvidenceInputs(
        kind=EvidenceKind.PAPER,
        lifecycle=normalize_paper_lifecycle(records),
        no_trades=tuple(no_trade_from_paper(records)),
        paper_epoch_ids=tuple(sorted({record.epoch_id for record in records})),
    )


def _research_symbols(args: CliArgs, evidence: EvidenceFile | None) -> tuple[str, ...]:
    if args.universe is not None:
        return load_universe_file(args.universe)
    return () if evidence is None else evidence.research_universe


def _merge_resets(
    from_file: Sequence[ResetRecord], events: Sequence[JournalEvent]
) -> tuple[ResetRecord, ...]:
    """Decision-file resets plus journal resets, de-duplicated and in a total order."""
    merged = {
        (reset.occurred_at_utc, reset.operator_id, reset.decision_ref): reset
        for reset in (*from_file, *resets_from_events(events))
    }
    return tuple(merged[key] for key in sorted(merged))


def _build_inputs(args: CliArgs, as_of: datetime, database: _DatabaseData | None) -> ReportInputs:
    decisions: DecisionsFile = load_decisions_file(args.decisions)
    evidence = None if args.evidence is None else load_evidence_file(args.evidence)
    entries = () if evidence is None else evidence.backtest
    scan = scan_family_facts(
        sheets_root=_SHEETS_ROOT,
        decisions=decisions,
        experiments=tuple(entry.experiment for entry in entries),
        flags_by_experiment={entry.experiment.experiment_id: entry.flags for entry in entries},
    )
    events: tuple[JournalEvent, ...] = () if database is None else database.journal_events
    return ReportInputs(
        as_of_utc=as_of,
        backtest=_backtest_inputs(entries, args.raw_root),
        paper=_paper_inputs(() if evidence is None else evidence.paper),
        live=(
            EvidenceInputs(kind=EvidenceKind.LIVE)
            if database is None
            else _live_inputs(database, args.raw_root)
        ),
        clock=clock_start_from_protocol(read_protocol_text(_REPO_ROOT)),
        research_symbols=_research_symbols(args, evidence),
        journal_events=events,
        families=scan.families,
        family_gate_facts=dict(scan.gate_facts),
        prior_evaluations=priors_from_events(events),
        resets=_merge_resets(decisions.resets, events),
    )


# --------------------------------------------------------------------------- #
# Database access: SELECT-only reads, plus the single explicit record step
# --------------------------------------------------------------------------- #

SessionFactoryFn = Callable[[str], Any]

_ENTRY_EXPIRY_EVENT_TYPE = "ENTRY_EXPIRY"
_JOURNAL_EVENT_TYPES = (
    LIVE_ORDERS_ENABLED_EVENT,
    LIVE_ORDERS_DISABLED_EVENT,
    _ENTRY_EXPIRY_EVENT_TYPE,
    KILL_GATE_EVENT_TYPE,
    QUESTION_APPROVED_EVENT_TYPE,
)
# psycopg's async mode cannot run on the Windows default (Proactor) event loop.
_LOOP_FACTORY = asyncio.SelectorEventLoop if sys.platform == "win32" else None


class _DatabaseReadError(Exception):
    """A database read failed; the message is the exception type name only."""


class _RecordError(Exception):
    """The KILL_GATE_EVALUATION append failed; the message is the exception type name only."""


@dataclass(frozen=True)
class _DatabaseData:
    journal_events: tuple[JournalEvent, ...]
    journal_rejected: int
    live: LiveRows


async def _dispose_bind(factory: Any) -> None:
    kwargs = getattr(factory, "kw", None)
    bind = kwargs.get("bind") if isinstance(kwargs, dict) else None
    dispose = getattr(bind, "dispose", None)
    if dispose is not None:
        with contextlib.suppress(Exception):  # cleanup only; never masks the real outcome
            await dispose()


async def _with_session[T](
    url: str, factory_fn: SessionFactoryFn, action: Callable[[Any], Awaitable[T]]
) -> T:
    factory = factory_fn(url)
    try:
        async with session_scope(factory) as session:
            return await action(session)
    finally:
        await _dispose_bind(factory)


async def _read_all(session: Any) -> _DatabaseData:
    journal = await read_journal_events(session, event_types=_JOURNAL_EVENT_TYPES)
    live = await read_live_rows(session)
    return _DatabaseData(journal.events, journal.rejected, live)


def _read_database(url: str, factory_fn: SessionFactoryFn) -> _DatabaseData:
    """Read journal events and live rows; any failure is reduced to its exception type name."""
    try:
        return asyncio.run(_with_session(url, factory_fn, _read_all), loop_factory=_LOOP_FACTORY)
    except Exception as exc:
        raise _DatabaseReadError(type(exc).__name__) from None


def _record_evaluation(url: str, factory_fn: SessionFactoryFn, event: JournalEvent) -> None:
    async def append(session: Any) -> None:
        await append_kill_gate_event(session, event)

    try:
        asyncio.run(_with_session(url, factory_fn, append), loop_factory=_LOOP_FACTORY)
    except Exception as exc:
        raise _RecordError(type(exc).__name__) from None


def _live_inputs(database: _DatabaseData, raw_root: Path) -> EvidenceInputs:
    """LIVE evidence from the read rows; join and reject counts go to the INCOMPLETE ledger."""
    rows = database.live
    expiry_events = [
        event for event in database.journal_events if event.event_type == _ENTRY_EXPIRY_EVENT_TYPE
    ]
    lifecycle = normalize_live_lifecycle(
        rows.signals, rows.approvals, rows.orders, rows.fills, expiry_events
    )
    outcomes = normalize_live_outcomes(rows.signals, rows.plans, rows.orders, rows.fills)
    candles, candle_notes = _candles_for(outcomes.outcomes, raw_root)
    notes: list[InputNote] = list(candle_notes)
    notes.extend(
        InputNote(join.name, "UNMATCHED_JOIN", join.unmatched)
        for join in lifecycle.joins
        if join.unmatched > 0
    )
    notes.extend(
        InputNote("live_lifecycle", reason, count)
        for reason, count in lifecycle.rejected
        if count > 0
    )
    notes.extend(
        InputNote(f"live_rows:{table}", "MALFORMED_ROW", count)
        for table, count in rows.rejected
        if count > 0
    )
    if database.journal_rejected > 0:
        notes.append(InputNote("journal_events", "MALFORMED_ROW", database.journal_rejected))
    incomplete_counts: dict[str, int] = {}
    for _signal_id, reason in outcomes.incomplete:
        incomplete_counts[reason.value] = incomplete_counts.get(reason.value, 0) + 1
    notes.extend(
        InputNote("live_outcomes", reason, incomplete_counts[reason])
        for reason in sorted(incomplete_counts)
    )
    return EvidenceInputs(
        kind=EvidenceKind.LIVE,
        outcomes=outcomes.outcomes,
        lifecycle=lifecycle.records,
        candles_by_symbol=candles,
        realized_r_by_signal=_realized_r_by_signal(outcomes.outcomes),
        notes=tuple(notes),
    )


# --------------------------------------------------------------------------- #
# Rendering and the only file writes
# --------------------------------------------------------------------------- #


def _render_pair(report: JournalDepthReport) -> tuple[str, bytes, bytes]:
    """(file stem, Markdown bytes, sidecar bytes), verified to agree before any write."""
    markdown = render_markdown(report)
    sidecar = sidecar_text(build_sidecar(report, markdown))
    problems = verify_render(markdown, sidecar, report=report)
    if problems:
        raise _RenderVerificationError("; ".join(problems))
    return report_file_stem(report), markdown.encode("utf-8"), sidecar.encode("utf-8")


def _write_pair(out_dir: Path, stem: str, markdown: bytes, sidecar: bytes) -> tuple[Path, Path]:
    """Write both files as raw bytes; a failed write removes any file of this pair."""
    report_path = out_dir / f"{stem}.md"
    sidecar_path = out_dir / f"{stem}.json"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        report_path.write_bytes(markdown)
        sidecar_path.write_bytes(sidecar)
    except OSError:
        report_path.unlink(missing_ok=True)
        sidecar_path.unlink(missing_ok=True)
        raise
    return report_path, sidecar_path


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

_EXPECTED_FAILURES = (
    EvidenceFileError,
    DecisionsFileError,
    PathConfinementError,
    AnalyticsInputError,
    KillGateInputError,
    RenderError,
    _RenderVerificationError,
    _DatabaseReadError,
    OSError,
)


def _reason(exc: Exception) -> str:
    """One-line failure reason; file-system errors are reduced to their type name."""
    if isinstance(exc, OSError):
        return f"file access failed ({type(exc).__name__})"
    if isinstance(exc, _RenderVerificationError):
        return f"rendered output failed verification ({exc})"
    if isinstance(exc, _DatabaseReadError):
        return f"database read failed ({exc})"
    return " ".join(str(exc).split()).rstrip(".")


def _fail(reason: str) -> int:
    print(f"Report not produced: {reason}. {_FAILURE_TAIL}", file=sys.stderr)
    return 1


_RECORD_REMINDER = (
    "Reminder: a human must commit recorded_terminal in docs/research/kill_gate_decisions.json "
    "for the CI registration tripwire; this CLI never edits that file."
)


def _database_url(args: CliArgs) -> str | None:
    """DATABASE_URL (read once from the environment) unless --no-db; blank counts as absent."""
    if args.no_db:
        return None
    url = os.environ.get("DATABASE_URL", "")
    return url if url.strip() != "" else None


def _record_step(url: str, factory_fn: SessionFactoryFn, report: JournalDepthReport) -> int:
    """The single write: append one content-hash KILL_GATE_EVALUATION (idempotent on replay)."""
    event = build_kill_gate_event(report.kill_gate.verdict)
    try:
        _record_evaluation(url, factory_fn, event)
    except _RecordError as exc:
        print(f"Record failed: {exc}.", file=sys.stderr)
        return 1
    state = report.kill_gate.verdict.state
    print(
        f"Recorded KILL_GATE_EVALUATION {event.journal_event_id} (state {state.value}). "
        "Replaying the same inputs is a no-op."
    )
    if state is KillGateState.INSUFFICIENT_EDGE:
        print(_RECORD_REMINDER)
    return 0


def _run(args: CliArgs, now_fn: ClockFn | None, session_factory_fn: SessionFactoryFn | None) -> int:
    database_url = _database_url(args)
    if args.record and database_url is None:
        raise _UsageError("--record requires a database (DATABASE_URL set and --no-db absent)")
    factory_fn = make_session_factory if session_factory_fn is None else session_factory_fn
    as_of = _resolve_as_of(args, now_fn)
    out_dir = confine_output_dir(args.out_dir, args.reports_root).resolve()
    database = None if database_url is None else _read_database(database_url, factory_fn)
    report = build_journal_depth_report(
        _build_inputs(args, as_of, database), base_seed=args.seed, resamples=args.resamples
    )
    stem, markdown, sidecar = _render_pair(report)
    report_path, sidecar_path = _write_pair(out_dir, stem, markdown, sidecar)
    print(f"Report: {report_path}")
    print(f"Sidecar: {sidecar_path}")
    print(f"Digest: sha256:{report.digest()}")
    print(f"Kill gate: {report.kill_gate.verdict.state.value}")
    if args.record and database_url is not None:
        return _record_step(database_url, factory_fn, report)
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    now_fn: ClockFn | None = None,
    session_factory_fn: SessionFactoryFn | None = None,
) -> int:
    """Run the CLI; returns the process exit code (0 produced, 1 not produced, 2 usage)."""
    try:
        args = parse_args(argv)
        return _run(args, now_fn, session_factory_fn)
    except SystemExit as exc:  # argparse --help
        return exc.code if isinstance(exc.code, int) else 2
    except _UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except _EXPECTED_FAILURES as exc:
        return _fail(_reason(exc))


if __name__ == "__main__":
    raise SystemExit(main())
