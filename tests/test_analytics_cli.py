"""End-to-end tests for the analytics CLI (Phase 10, plan 10-12, D-01, D-03, D-04, D-05).

The CLI is the single edge that composes the two adapters and the pure core: files in,
Markdown plus JSON sidecar out, four stdout lines, exit codes 0/1/2/3. Tests call `main` with
argv lists and capture output through capsys (subprocess-free); every output root is a
tmp_path (`--reports-root`), so nothing is ever written under the repository.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import Select
from sqlalchemy.sql.dml import Insert
from src.adapters.binance_usdm import Kline
from src.analytics.cli import main
from src.data.store import publish_batch
from src.db.mappers import journal_to_row, signal_to_row
from src.db.models import JournalEventRow, SignalRow
from src.domain.enums import SignalStatus
from src.domain.journal import JournalEvent, content_hash_event_id
from src.domain.registry import (
    ParameterSetMutated,
    RegistrySchemaMismatch,
    StrategyKeyOutsideRegistry,
    UnregisteredParameterSet,
    load_parameter_set,
)
from src.domain.signal import Signal

REPO = Path(__file__).resolve().parents[1]
EVIDENCE_FIXTURE = REPO / "tests" / "fixtures" / "phase10" / "loaders" / "evidence_sample.json"
AS_OF = "2027-04-01T00:00:00+00:00"
FAMILIES = ("breakout-retest", "range-mr", "trend-pullback")
# The injected edge clock for --record runs: one hour after AS_OF (never the real clock).
RECORD_NOW = datetime(2027, 4, 1, 1, 0, tzinfo=UTC)
COPY_TAIL = "No file was written. Fix the cause and re-run journal-report.ps1 with the same -AsOf."


@pytest.fixture(autouse=True)
def _no_ambient_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """The developer shell may export DATABASE_URL; tests must never reach a real database."""
    monkeypatch.delenv("DATABASE_URL", raising=False)


def _decisions_file(tmp_path: Path, families: list[dict[str, Any]] | None = None) -> Path:
    path = tmp_path / "decisions.json"
    path.write_text(
        json.dumps(
            {
                "schema": "kill-gate-decisions/1",
                "families": families or [],
                "resets": [],
                "recorded_terminal": None,
            }
        ),
        encoding="utf-8",
    )
    return path


def _publish_candles(raw_root: Path) -> None:
    """1m BTCUSDT candles covering the fixture trade T-1 (2026-01-05 10:00 to 14:00 UTC)."""
    start = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
    klines = [
        Kline(
            symbol="BTCUSDT",
            interval="1m",
            open_time_utc=start + timedelta(minutes=i),
            close_time_utc=start + timedelta(minutes=i, seconds=59),
            open=Decimal("100.00"),
            high=Decimal("111.00") if i == 200 else Decimal("101.00"),
            low=Decimal("99.00") if i == 100 else Decimal("100.00"),
            close=Decimal("100.00"),
            volume=Decimal("1"),
            quote_volume=Decimal("1"),
            trade_count=1,
        )
        for i in range(241)
    ]
    publish_batch(klines, interval="1m", symbol="BTCUSDT", raw_root=raw_root)


class _Env:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.reports_root = tmp_path / "reports"
        self.raw_root = tmp_path / "raw"
        self.decisions = _decisions_file(tmp_path)
        self.evidence = EVIDENCE_FIXTURE
        _publish_candles(self.raw_root)

    def argv(self, *extra: str, as_of: str | None = AS_OF) -> list[str]:
        base = [
            "--evidence",
            str(self.evidence),
            "--decisions",
            str(self.decisions),
            "--raw-root",
            str(self.raw_root),
            "--reports-root",
            str(self.reports_root),
        ]
        if as_of is not None:
            base = ["--as-of", as_of, *base]
        return [*base, *extra]

    def files(self) -> list[Path]:
        if not self.reports_root.exists():
            return []
        return sorted(path for path in self.reports_root.rglob("*") if path.is_file())


@pytest.fixture
def env(tmp_path: Path) -> _Env:
    return _Env(tmp_path)


def _run(
    capsys: pytest.CaptureFixture[str], argv: list[str], **kwargs: Any
) -> tuple[int, str, str]:
    capsys.readouterr()
    code = main(argv, **kwargs)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _stdout_lines(out: str) -> list[str]:
    return out.splitlines()


def _write_evidence(path: Path, backtest: list[dict[str, Any]]) -> Path:
    document = json.loads(EVIDENCE_FIXTURE.read_text(encoding="utf-8"))
    document["backtest"] = backtest
    document["paper"] = []
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _candidate_experiment(family: str, role: str) -> dict[str, Any]:
    template = json.loads(EVIDENCE_FIXTURE.read_text(encoding="utf-8"))["backtest"][0]
    experiment = dict(template["experiment"])
    experiment["experiment_id"] = hashlib.sha256(f"exp-{family}-{role}".encode()).hexdigest()
    experiment["parameter_set_hash"] = load_parameter_set(family, "baseline-v1").parameter_set_hash
    experiment["parameter_set_id"] = "baseline-v1"
    experiment["run_type"] = "CANDIDATE"
    return {
        "experiment": experiment,
        "trades": [],
        "contexts": {},
        "flags": dict(template["flags"]),
    }


def test_tracer_cli_end_to_end(env: _Env, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _run(capsys, env.argv())
    assert code == 0, err
    assert err == ""
    lines = _stdout_lines(out)
    assert len(lines) == 4
    assert lines[0].startswith("Report: ")
    assert lines[1].startswith("Sidecar: ")
    assert lines[2].startswith("Digest: sha256:")
    assert lines[3] == "Kill gate: WITHIN_BUDGET"

    report_path = Path(lines[0].removeprefix("Report: "))
    sidecar_path = Path(lines[1].removeprefix("Sidecar: "))
    assert report_path.is_file()
    assert sidecar_path.is_file()
    assert report_path.suffix == ".md"
    assert sidecar_path.suffix == ".json"
    assert report_path.stem == sidecar_path.stem
    assert report_path.stem.startswith("journal-depth-20270401T000000Z-")
    assert report_path.parent == env.reports_root.resolve()

    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert lines[2] == "Digest: sha256:" + sidecar["report_digest"]
    assert report_path.stem.endswith(sidecar["report_digest"][:12])
    assert sidecar["markdown_sha256"] == hashlib.sha256(report_path.read_bytes()).hexdigest()
    markdown = report_path.read_text(encoding="utf-8")
    assert "# Journal Depth + Kill-Gate Report" in markdown
    assert "2027-04-01" in markdown


def test_output_directory_holds_exactly_two_files(
    env: _Env, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, err = _run(capsys, env.argv())
    assert code == 0, err
    files = env.files()
    assert sorted(path.suffix for path in files) == [".json", ".md"]


def test_files_are_byte_identical_across_two_runs_and_names_are_stable(
    env: _Env, capsys: pytest.CaptureFixture[str]
) -> None:
    code_a, out_a, err_a = _run(capsys, env.argv())
    assert code_a == 0, err_a
    first = {path.name: path.read_bytes() for path in env.files()}
    code_b, out_b, err_b = _run(capsys, env.argv())
    assert code_b == 0, err_b
    second = {path.name: path.read_bytes() for path in env.files()}
    assert first == second
    assert len(first) == 2
    assert out_a == out_b


def test_a_different_as_of_yields_different_file_names(
    env: _Env, capsys: pytest.CaptureFixture[str]
) -> None:
    code_a, _, err_a = _run(capsys, env.argv(as_of="2027-04-01T00:00:00+00:00"))
    assert code_a == 0, err_a
    names_a = {path.name for path in env.files()}
    code_b, _, err_b = _run(capsys, env.argv(as_of="2027-04-02T00:00:00+00:00"))
    assert code_b == 0, err_b
    names_both = {path.name for path in env.files()}
    assert len(names_both) == 4
    assert names_a < names_both


def test_output_bytes_are_utf8_lf_without_carriage_returns(
    env: _Env, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, err = _run(capsys, env.argv())
    assert code == 0, err
    for path in env.files():
        data = path.read_bytes()
        assert b"\r" not in data
        assert data.endswith(b"\n")
        assert not data.startswith(b"\xef\xbb\xbf")
        data.decode("utf-8")


def test_clock_is_never_read_when_as_of_is_given(
    env: _Env, capsys: pytest.CaptureFixture[str]
) -> None:
    def exploding_clock() -> datetime:
        raise AssertionError("the wall clock must not be read when --as-of is given")

    code, _, err = _run(capsys, env.argv(), now_fn=exploding_clock)
    assert code == 0, err


def test_clock_is_read_exactly_once_when_as_of_is_omitted(
    env: _Env, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[int] = []

    def fixed_clock() -> datetime:
        calls.append(1)
        return datetime(2027, 4, 1, 12, 30, 45, 987654, tzinfo=UTC)

    code, out, err = _run(capsys, env.argv(as_of=None), now_fn=fixed_clock)
    assert code == 0, err
    assert len(calls) == 1
    report_path = Path(_stdout_lines(out)[0].removeprefix("Report: "))
    assert report_path.stem.startswith("journal-depth-20270401T123045Z-")
    markdown = report_path.read_text(encoding="utf-8")
    assert "2027-04-01T12:30:45+00:00" in markdown
    assert "987654" not in markdown


def test_naive_as_of_exits_two_and_writes_nothing(
    env: _Env, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = _run(capsys, env.argv(as_of="2027-04-01T00:00:00"))
    assert code == 2
    assert out == ""
    assert "as-of" in err
    assert env.files() == []


def test_unparseable_as_of_exits_two_and_writes_nothing(
    env: _Env, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, err = _run(capsys, env.argv(as_of="not-a-timestamp"))
    assert code == 2
    assert "as-of" in err
    assert env.files() == []


def test_resamples_below_the_minimum_exits_two(
    env: _Env, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, err = _run(capsys, env.argv("--resamples", "50"))
    assert code == 2
    assert "resamples" in err
    assert env.files() == []


def test_unknown_flag_exits_two(env: _Env, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = _run(capsys, env.argv("--not-a-flag"))
    assert code == 2
    assert err != ""
    assert env.files() == []


def test_malformed_evidence_exits_one_with_the_copy_and_writes_no_files(
    env: _Env, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    broken = tmp_path / "broken-evidence.json"
    broken.write_text('{"schema": "analytics-evidence/1", "backtest": 5}', encoding="utf-8")
    env.evidence = broken
    code, out, err = _run(capsys, env.argv())
    assert code == 1
    assert out == ""
    assert err.startswith("Report not produced: ")
    assert err.rstrip("\n").endswith(COPY_TAIL)
    assert env.files() == []


def test_missing_evidence_file_exits_one_without_leaking_the_path(
    env: _Env, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    env.evidence = tmp_path / "nope" / "missing.json"
    code, _, err = _run(capsys, env.argv())
    assert code == 1
    assert err.startswith("Report not produced: ")
    assert env.files() == []


def test_out_dir_escape_exits_one_and_writes_nothing(
    env: _Env, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    escape = tmp_path / "reports" / ".." / "outside"
    code, out, err = _run(capsys, env.argv("--out-dir", str(escape)))
    assert code == 1
    assert out == ""
    assert err.startswith("Report not produced: ")
    assert not (tmp_path / "outside").exists()
    assert env.files() == []


def test_out_dir_inside_the_root_is_created_and_used(
    env: _Env, capsys: pytest.CaptureFixture[str]
) -> None:
    target = env.reports_root / "nested" / "run"
    code, out, err = _run(capsys, env.argv("--out-dir", str(target)))
    assert code == 0, err
    report_path = Path(_stdout_lines(out)[0].removeprefix("Report: "))
    assert report_path.parent == target.resolve()
    assert len(env.files()) == 2


def test_duplicate_trade_id_across_experiments_exits_one(
    env: _Env, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    document = json.loads(EVIDENCE_FIXTURE.read_text(encoding="utf-8"))
    first = document["backtest"][0]
    second = json.loads(json.dumps(first))
    second["experiment"]["experiment_id"] = hashlib.sha256(b"other-experiment").hexdigest()
    document["backtest"] = [first, second]
    path = tmp_path / "duplicate-trades.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    env.evidence = path
    code, _, err = _run(capsys, env.argv())
    assert code == 1
    assert "duplicate trade_id" in err
    assert env.files() == []


@pytest.mark.parametrize(
    ("target", "exc"),
    [
        ("scan_family_facts", RegistrySchemaMismatch("C:/secret/params/x/baseline-v1.toml: bad")),
        ("scan_family_facts", StrategyKeyOutsideRegistry("C:/secret/params/x.toml: key")),
        ("scan_family_facts", UnregisteredParameterSet("secret-family/secret-set")),
        ("scan_family_facts", ParameterSetMutated("C:/secret/params/x.toml: hash")),
        ("read_protocol_text", UnicodeDecodeError("utf-8", b"\xff", 0, 1, "secret-detail")),
        ("clock_start_from_protocol", ValueError("secret-detail from the clock")),
    ],
)
def test_unexpected_input_failures_exit_one_with_the_exception_type_only(
    env: _Env,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    exc: Exception,
) -> None:
    """WR-03: registry / decode / value failures keep the exit-1 name-only contract."""

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise exc

    monkeypatch.setattr(f"src.analytics.cli.{target}", boom)
    code, out, err = _run(capsys, env.argv())
    assert code == 1
    assert out == ""
    assert err.startswith(f"Report not produced: input could not be read ({type(exc).__name__})")
    assert err.rstrip("\n").endswith(COPY_TAIL)
    assert "secret" not in err
    assert env.files() == []


def test_a_missing_candle_store_still_produces_a_report(
    env: _Env, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    env.raw_root = tmp_path / "no-such-raw-root"
    code, out, err = _run(capsys, env.argv())
    assert code == 0, err
    report_path = Path(_stdout_lines(out)[0].removeprefix("Report: "))
    assert "NO_1M_COVERAGE" in report_path.read_text(encoding="utf-8")


def test_the_universe_flag_changes_the_research_universe_provenance(
    env: _Env, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code_a, out_a, err_a = _run(capsys, env.argv())
    assert code_a == 0, err_a
    universe = tmp_path / "universe.json"
    universe.write_text('["BTCUSDT"]', encoding="utf-8")
    code_b, out_b, err_b = _run(capsys, env.argv("--universe", str(universe)))
    assert code_b == 0, err_b
    digest_a = _stdout_lines(out_a)[2]
    digest_b = _stdout_lines(out_b)[2]
    assert digest_a != digest_b


def _universe_status(out: str) -> str:
    status: str = _sidecar_of(out)["report"]["provenance"]["research_universe_status"]
    return status


def test_research_universe_is_verified_against_the_experiment_universe_hash(
    env: _Env, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """WR-07: the recorded ExperimentRecord.universe_hash is actually checked."""
    code, out, err = _run(capsys, env.argv())
    assert code == 0, err
    assert _universe_status(out) == "VERIFIED"

    universe = tmp_path / "universe.json"
    universe.write_text('["BTCUSDT"]', encoding="utf-8")
    code, out, err = _run(capsys, env.argv("--universe", str(universe)))
    assert code == 0, err
    assert _universe_status(out) == "UNVERIFIED_UNIVERSE"


def test_candidate_experiments_on_different_universes_are_unverified(
    env: _Env, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    first = _candidate_experiment("trend-pullback", "u1")
    second = _candidate_experiment("trend-pullback", "u2")
    second["experiment"]["universe_hash"] = hashlib.sha256(b"another-universe").hexdigest()
    env.evidence = _write_evidence(tmp_path / "mixed-universe.json", [first, second])
    code, out, err = _run(capsys, env.argv())
    assert code == 0, err
    assert _universe_status(out) == "UNVERIFIED_UNIVERSE"


def test_without_candidate_experiments_the_universe_check_is_not_applicable(
    env: _Env, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    env.evidence = _write_evidence(tmp_path / "no-experiments.json", [])
    code, out, err = _run(capsys, env.argv())
    assert code == 0, err
    assert _universe_status(out) == "NOT_APPLICABLE"


def test_the_seed_and_resamples_flags_are_echoed_in_the_sidecar(
    env: _Env, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = _run(capsys, env.argv("--resamples", "200", "--seed", "7"))
    assert code == 0, err
    sidecar_path = Path(_stdout_lines(out)[1].removeprefix("Sidecar: "))
    report = json.loads(sidecar_path.read_text(encoding="utf-8"))["report"]
    assert report["resamples"] == 200
    assert report["base_seed"] == 7


def test_unmapped_candidate_experiments_are_counted_in_the_incomplete_ledger(
    env: _Env, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """WR-02: a CANDIDATE run matching no registered family is counted, never dropped."""
    unmapped = _candidate_experiment("trend-pullback", "unmapped")
    unmapped["experiment"]["parameter_set_hash"] = "9" * 64
    env.evidence = _write_evidence(tmp_path / "unmapped-evidence.json", [unmapped])
    code, out, err = _run(capsys, env.argv())
    assert code == 0, err
    ledger = _sidecar_of(out)["report"]["incomplete_ledger"]
    assert {
        "evidence": "BACKTEST",
        "input_name": "family_scan:unknown_experiments",
        "reason": "UNMATCHED_JOIN",
        "count": 1,
    } in ledger


def test_terminal_state_exits_zero_with_the_calm_banner(
    env: _Env, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    backtest: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    for family in FAMILIES:
        development = _candidate_experiment(family, "dev")
        validation = _candidate_experiment(family, "val")
        backtest.extend([development, validation])
        decisions.append(
            {
                "family_id": family,
                "status": "TESTED_FAIL",
                "decision_ref": f"DEC-TEST-{family}",
                "decided_at_utc": "2026-12-01T00:00:00+00:00",
                "development_experiment_ids": [development["experiment"]["experiment_id"]],
                "validation_experiment_ids": [validation["experiment"]["experiment_id"]],
            }
        )
    env.evidence = _write_evidence(tmp_path / "terminal-evidence.json", backtest)
    env.decisions = _decisions_file(tmp_path, decisions)

    code, out, err = _run(capsys, env.argv(as_of="2027-04-01T00:00:00+00:00"))
    assert code == 0, err
    lines = _stdout_lines(out)
    assert lines[3] == "Kill gate: INSUFFICIENT_EDGE"
    markdown = Path(lines[0].removeprefix("Report: ")).read_text(encoding="utf-8")
    assert "NO_TRADE / INSUFFICIENT EDGE." in markdown
    assert "This is a valid terminal outcome, not an error." in markdown


# --------------------------------------------------------------------------- #
# Read-only database path and the explicit --record step (plan 10-12, task 2)
# --------------------------------------------------------------------------- #

DATABASE_URL = "postgresql+psycopg://trader:s3cr3t-pw@db.internal.example:5432/trading"
KGE = "KILL_GATE_EVALUATION"
RESET_EVENT = "KILL_GATE_QUESTION_APPROVED"
_JOURNAL_COLUMNS = tuple(JournalEventRow.__table__.columns.keys())


def _journal_event(
    event_type: str, at: str, payload: dict[str, str], entity_id: str = "KILL_GATE_D013"
) -> JournalEvent:
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    moment = datetime.fromisoformat(at)
    return JournalEvent(
        journal_event_id=content_hash_event_id(
            prefix="test",
            event_type=event_type,
            entity_id=entity_id,
            occurred_at_utc=moment,
            payload_json=payload_json,
        ),
        occurred_at_utc=moment,
        event_type=event_type,
        entity_type="KillGate",
        entity_id=entity_id,
        correlation_id="test_correlation",
        payload_json=payload_json,
    )


def _live_signal(signal_id: str = "SIG-LIVE-1") -> Signal:
    return Signal(
        signal_id=signal_id,
        strategy_id="trend-pullback",
        strategy_version="v2.0.0",
        parameter_set_id="baseline-v1",
        parameter_set_hash="b" * 64,
        symbol="BTCUSDT",
        direction="LONG",
        setup_type="pullback",
        source_timeframe="1h",
        source_candle_close_utc=datetime(2027, 3, 1, 12, 0, tzinfo=UTC),
        detected_at_utc=datetime(2027, 3, 1, 12, 5, tzinfo=UTC),
        status=SignalStatus.DETECTED,
        expires_at_utc=datetime(2027, 3, 1, 16, 0, tzinfo=UTC),
        invalidated_at_utc=None,
    )


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeStore:
    """In-memory stand-in for the database: canned rows, every statement recorded."""

    def __init__(self) -> None:
        self.journal: list[JournalEventRow] = []
        self.signals: list[Any] = []
        self.statements: list[Any] = []
        self.commits = 0
        self.fail_reads: Exception | None = None
        self.fail_inserts: Exception | None = None

    def add_events(self, *events: JournalEvent) -> None:
        self.journal.extend(journal_to_row(event) for event in events)

    def rows_for(self, entity: Any) -> list[Any]:
        if entity is JournalEventRow:
            return self.journal
        if entity is SignalRow:
            return self.signals
        return []

    def inserts(self) -> list[Insert]:
        return [item for item in self.statements if isinstance(item, Insert)]

    def kill_gate_ids(self) -> list[str]:
        return [row.journal_event_id for row in self.journal if row.event_type == KGE]


class _FakeSession:
    def __init__(self, store: _FakeStore) -> None:
        self.store = store

    def get_bind(self) -> Any:
        return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    async def execute(self, statement: Any) -> _Result:
        self.store.statements.append(statement)
        if isinstance(statement, Insert):
            if self.store.fail_inserts is not None:
                raise self.store.fail_inserts
            params = statement.compile(dialect=postgresql.dialect()).params
            if params["journal_event_id"] not in {r.journal_event_id for r in self.store.journal}:
                self.store.journal.append(
                    JournalEventRow(**{name: params[name] for name in _JOURNAL_COLUMNS})
                )
            return _Result([])
        if self.store.fail_reads is not None:
            raise self.store.fail_reads
        return _Result(list(self.store.rows_for(statement.column_descriptions[0]["entity"])))

    async def commit(self) -> None:
        self.store.commits += 1


class _FakeSessionContext:
    def __init__(self, store: _FakeStore) -> None:
        self._store = store

    async def __aenter__(self) -> _FakeSession:
        return _FakeSession(self._store)

    async def __aexit__(self, *exc_info: object) -> None:
        return None


class _FakeFactory:
    def __init__(self, store: _FakeStore) -> None:
        self.store = store
        self.urls: list[str] = []

    def factory_fn(self, url: str) -> Any:
        self.urls.append(url)
        return lambda: _FakeSessionContext(self.store)


def _db_run(
    env: _Env,
    fake: _FakeFactory,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    *extra: str,
    as_of: str | None = AS_OF,
    now: datetime = RECORD_NOW,
) -> tuple[int, str, str]:
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    return _run(
        capsys,
        env.argv(*extra, as_of=as_of),
        session_factory_fn=fake.factory_fn,
        now_fn=lambda: now,
    )


def _sidecar_of(out: str) -> dict[str, Any]:
    path = Path(_stdout_lines(out)[1].removeprefix("Sidecar: "))
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _assert_no_secret_anywhere(env: _Env, out: str, err: str) -> None:
    for secret in (DATABASE_URL, "s3cr3t-pw", "db.internal.example"):
        assert secret not in out
        assert secret not in err
        for path in env.files():
            assert secret not in path.read_text(encoding="utf-8")


def _terminal_prior() -> JournalEvent:
    return _journal_event(
        KGE,
        "2027-03-25T00:00:00+00:00",
        {"state": "INSUFFICIENT_EDGE", "evaluated_at_utc": "2027-03-25T00:00:00+00:00"},
    )


def test_db_rows_populate_the_live_block_and_the_posture(
    env: _Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _FakeStore()
    store.signals.append(signal_to_row(_live_signal()))
    store.add_events(
        _journal_event("LIVE_ORDERS_ENABLED", "2027-03-01T00:00:00+00:00", {}, "LIVE_ORDERS"),
        _journal_event("LIVE_ORDERS_DISABLED", "2027-03-02T00:00:00+00:00", {}, "LIVE_ORDERS"),
    )
    fake = _FakeFactory(store)
    code, out, err = _db_run(env, fake, capsys, monkeypatch)
    assert code == 0, err
    assert len(_stdout_lines(out)) == 4
    report = _sidecar_of(out)["report"]
    assert report["live_posture"] == "LIVE_ORDERS_DISABLED"
    live = next(block for block in report["evidence"] if block["kind"] == "LIVE")
    assert live["has_data"] is True
    assert fake.urls == [DATABASE_URL]
    _assert_no_secret_anywhere(env, out, err)


def test_db_report_path_executes_only_select_statements(
    env: _Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _FakeStore()
    store.signals.append(signal_to_row(_live_signal()))
    code, _, err = _db_run(env, _FakeFactory(store), capsys, monkeypatch)
    assert code == 0, err
    assert store.statements
    assert all(isinstance(statement, Select) for statement in store.statements)
    assert store.inserts() == []
    assert store.commits == 0


def test_db_without_rows_reports_an_unknown_posture_and_empty_live_block(
    env: _Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    code, out, err = _db_run(env, _FakeFactory(_FakeStore()), capsys, monkeypatch)
    assert code == 0, err
    report = _sidecar_of(out)["report"]
    assert report["live_posture"] == "UNKNOWN"
    live = next(block for block in report["evidence"] if block["kind"] == "LIVE")
    assert live["has_data"] is False


def test_db_prior_terminal_evaluation_keeps_the_state_sticky(
    env: _Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _FakeStore()
    store.add_events(_terminal_prior())
    code, out, err = _db_run(env, _FakeFactory(store), capsys, monkeypatch)
    assert code == 0, err
    assert _stdout_lines(out)[3] == "Kill gate: INSUFFICIENT_EDGE"


def test_db_reset_event_reopens_research_after_a_prior_terminal(
    env: _Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _FakeStore()
    store.add_events(
        _terminal_prior(),
        _journal_event(
            RESET_EVENT,
            "2027-03-28T00:00:00+00:00",
            {"operator_id": "op-db", "decision_ref": "DEC-DB-RESET"},
        ),
    )
    code, out, err = _db_run(env, _FakeFactory(store), capsys, monkeypatch)
    assert code == 0, err
    lines = _stdout_lines(out)
    assert lines[3] == "Kill gate: WITHIN_BUDGET"
    assert "DEC-DB-RESET" in Path(lines[0].removeprefix("Report: ")).read_text(encoding="utf-8")


def test_db_and_decisions_file_resets_are_merged_and_deduplicated(
    env: _Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    reset = {
        "operator_id": "op-both",
        "decision_ref": "DEC-BOTH-RESET",
        "occurred_at_utc": "2027-03-28T00:00:00+00:00",
    }
    env.decisions.write_text(
        json.dumps(
            {
                "schema": "kill-gate-decisions/1",
                "families": [],
                "resets": [reset],
                "recorded_terminal": None,
            }
        ),
        encoding="utf-8",
    )
    store = _FakeStore()
    store.add_events(
        _terminal_prior(),
        _journal_event(
            RESET_EVENT,
            "2027-03-28T00:00:00+00:00",
            {"operator_id": "op-both", "decision_ref": "DEC-BOTH-RESET"},
        ),
    )
    code, out, err = _db_run(env, _FakeFactory(store), capsys, monkeypatch)
    assert code == 0, err
    assert _stdout_lines(out)[3] == "Kill gate: WITHIN_BUDGET"


@pytest.mark.parametrize(
    "payload",
    [
        {"state": "NOT_A_STATE", "evaluated_at_utc": "2027-03-25T00:00:00+00:00"},
        {"state": "INSUFFICIENT_EDGE", "evaluated_at_utc": "2027-03-25T00:00:00"},
        {"evaluated_at_utc": "2027-03-25T00:00:00+00:00"},
    ],
)
def test_db_unparseable_kill_gate_evaluation_fails_closed(
    env: _Env,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, str],
) -> None:
    """WR-11: a corrupted (possibly terminal) evaluation never silently disappears."""
    store = _FakeStore()
    store.add_events(_journal_event(KGE, "2027-03-25T00:00:00+00:00", payload))
    code, out, err = _db_run(env, _FakeFactory(store), capsys, monkeypatch)
    assert code == 1
    assert out == ""
    assert "KILL_GATE_EVALUATION" in err
    assert env.files() == []


def test_db_unparseable_reset_event_is_counted_in_the_ledger(
    env: _Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _FakeStore()
    store.add_events(
        _terminal_prior(),
        _journal_event(RESET_EVENT, "2027-03-28T00:00:00+00:00", {"operator_id": "op-db"}),
    )
    code, out, err = _db_run(env, _FakeFactory(store), capsys, monkeypatch)
    assert code == 0, err
    assert _stdout_lines(out)[3] == "Kill gate: INSUFFICIENT_EDGE"
    ledger = _sidecar_of(out)["report"]["incomplete_ledger"]
    assert {
        "evidence": "LIVE",
        "input_name": "journal_events:KILL_GATE_QUESTION_APPROVED",
        "reason": "MALFORMED_ROW",
        "count": 1,
    } in ledger


def test_db_failure_exits_one_with_only_the_exception_type(
    env: _Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _FakeStore()
    store.fail_reads = RuntimeError(f"cannot connect to {DATABASE_URL} password=s3cr3t-pw")
    code, out, err = _db_run(env, _FakeFactory(store), capsys, monkeypatch)
    assert code == 1
    assert out == ""
    assert err.startswith("Report not produced: database read failed (RuntimeError). ")
    assert err.rstrip("\n").endswith(COPY_TAIL)
    _assert_no_secret_anywhere(env, out, err)
    assert env.files() == []


def test_db_factory_failure_never_echoes_the_database_url(
    env: _Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", "not-an-async-url-carrying-s3cr3t-pw")
    code, out, err = _run(capsys, env.argv())
    assert code == 1
    assert "database read failed (ValueError)" in err
    assert "s3cr3t-pw" not in out + err
    assert env.files() == []


def test_no_db_flag_ignores_the_environment_url(
    env: _Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeFactory(_FakeStore())
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    code, _, err = _run(capsys, env.argv("--no-db"), session_factory_fn=fake.factory_fn)
    assert code == 0, err
    assert fake.urls == []
    assert fake.store.statements == []


def test_record_appends_one_kill_gate_evaluation_and_prints_the_confirmation(
    env: _Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _FakeStore()
    store.signals.append(signal_to_row(_live_signal()))
    code, out, err = _db_run(env, _FakeFactory(store), capsys, monkeypatch, "--record")
    assert code == 0, err
    lines = _stdout_lines(out)
    assert len(lines) == 5
    assert lines[3] == "Kill gate: WITHIN_BUDGET"
    (event_id,) = store.kill_gate_ids()
    assert lines[4] == (
        f"Recorded KILL_GATE_EVALUATION {event_id} (state WITHIN_BUDGET). "
        "Replaying the same inputs is a no-op."
    )
    inserts = store.inserts()
    assert len(inserts) == 1
    params = inserts[0].compile(dialect=postgresql.dialect()).params
    assert params["event_type"] == KGE
    assert all(isinstance(item, Select) for item in store.statements if item is not inserts[0])
    _assert_no_secret_anywhere(env, out, err)


def test_record_is_idempotent_for_the_same_inputs_and_as_of(
    env: _Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _FakeStore()
    fake = _FakeFactory(store)
    code_a, out_a, err_a = _db_run(env, fake, capsys, monkeypatch, "--record")
    assert code_a == 0, err_a
    code_b, out_b, err_b = _db_run(env, fake, capsys, monkeypatch, "--record")
    assert code_b == 0, err_b
    assert _stdout_lines(out_a)[4] == _stdout_lines(out_b)[4]
    assert len(store.kill_gate_ids()) == 1
    assert len(store.inserts()) == 2
    assert out_a == out_b


def test_record_of_a_terminal_state_prints_the_human_commit_reminder(
    env: _Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _FakeStore()
    store.add_events(_terminal_prior())
    code, out, err = _db_run(env, _FakeFactory(store), capsys, monkeypatch, "--record")
    assert code == 0, err
    assert "(state INSUFFICIENT_EDGE)" in out
    assert "kill_gate_decisions.json" in out
    assert "recorded_terminal" in out


def test_record_without_a_database_url_exits_two_and_writes_nothing(
    env: _Env, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = _run(capsys, env.argv("--record"))
    assert code == 2
    assert out == ""
    assert "--record" in err
    assert env.files() == []


def test_record_with_the_no_db_flag_exits_two_and_writes_nothing(
    env: _Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeFactory(_FakeStore())
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    code, out, err = _run(
        capsys, env.argv("--record", "--no-db"), session_factory_fn=fake.factory_fn
    )
    assert code == 2
    assert out == ""
    assert "--record" in err
    assert fake.urls == []
    assert env.files() == []


def _decisions_doc(
    *,
    families: list[dict[str, Any]] | None = None,
    resets: list[dict[str, Any]] | None = None,
    recorded_terminal: dict[str, Any] | None = None,
) -> str:
    return json.dumps(
        {
            "schema": "kill-gate-decisions/1",
            "families": families or [],
            "resets": resets or [],
            "recorded_terminal": recorded_terminal,
        }
    )


_COMMITTED_TERMINAL = {
    "state": "INSUFFICIENT_EDGE",
    "decision_ref": "DEC-TEST-terminal",
    "recorded_at_utc": "2027-03-25T00:00:00+00:00",
    "families_at_record": list(FAMILIES),
}


def test_committed_recorded_terminal_keeps_the_state_sticky_without_a_database(
    env: _Env, capsys: pytest.CaptureFixture[str]
) -> None:
    """CR-01: the committed mirror alone keeps INSUFFICIENT_EDGE sticky (no DB, --no-db)."""
    env.decisions.write_text(_decisions_doc(recorded_terminal=_COMMITTED_TERMINAL), "utf-8")
    code, out, err = _run(capsys, env.argv("--no-db"))
    assert code == 0, err
    assert _stdout_lines(out)[3] == "Kill gate: INSUFFICIENT_EDGE"


def test_committed_recorded_terminal_and_the_same_db_event_are_deduplicated(
    env: _Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    env.decisions.write_text(_decisions_doc(recorded_terminal=_COMMITTED_TERMINAL), "utf-8")
    store = _FakeStore()
    store.add_events(_terminal_prior())
    code, out, err = _db_run(env, _FakeFactory(store), capsys, monkeypatch)
    assert code == 0, err
    assert _stdout_lines(out)[3] == "Kill gate: INSUFFICIENT_EDGE"
    verdict = _sidecar_of(out)["report"]["kill_gate"]["verdict"]
    assert verdict["prior_terminal_count"] == 1


def test_committed_recorded_terminal_is_cleared_by_a_later_recorded_reset(
    env: _Env, capsys: pytest.CaptureFixture[str]
) -> None:
    reset = {
        "operator_id": "op-file",
        "decision_ref": "DEC-FILE-RESET",
        "occurred_at_utc": "2027-03-28T00:00:00+00:00",
    }
    env.decisions.write_text(
        _decisions_doc(resets=[reset], recorded_terminal=_COMMITTED_TERMINAL), "utf-8"
    )
    code, out, err = _run(capsys, env.argv("--no-db"))
    assert code == 0, err
    assert _stdout_lines(out)[3] == "Kill gate: WITHIN_BUDGET"


def test_record_without_an_evidence_file_exits_two_and_writes_nothing(
    env: _Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """WR-09: a recorded verdict is always derived from the evidence the decisions cite."""
    store = _FakeStore()
    argv = [item for item in env.argv("--record") if item != str(env.evidence)]
    argv.remove("--evidence")
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    code, out, err = _run(
        capsys,
        argv,
        session_factory_fn=_FakeFactory(store).factory_fn,
        now_fn=lambda: RECORD_NOW,
    )
    assert code == 2
    assert out == ""
    assert "--record requires --evidence" in err
    assert store.inserts() == []
    assert env.files() == []


def test_tested_decisions_without_an_evidence_file_fail_with_a_clear_reason(
    env: _Env, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    development = _candidate_experiment("trend-pullback", "dev")
    validation = _candidate_experiment("trend-pullback", "val")
    env.decisions = _decisions_file(
        tmp_path,
        [
            {
                "family_id": "trend-pullback",
                "status": "TESTED_FAIL",
                "decision_ref": "DEC-TEST-trend",
                "decided_at_utc": "2026-12-01T00:00:00+00:00",
                "development_experiment_ids": [development["experiment"]["experiment_id"]],
                "validation_experiment_ids": [validation["experiment"]["experiment_id"]],
            }
        ],
    )
    argv = [item for item in env.argv() if item != str(env.evidence)]
    argv.remove("--evidence")
    code, out, err = _run(capsys, argv)
    assert code == 1
    assert out == ""
    assert "--evidence" in err
    assert env.files() == []


def test_record_refuses_a_future_as_of_and_writes_nothing(
    env: _Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """WR-04: the journal never receives an evaluation instant later than the edge clock."""
    store = _FakeStore()
    code, out, err = _db_run(
        env,
        _FakeFactory(store),
        capsys,
        monkeypatch,
        "--record",
        as_of="2030-01-01T00:00:00+00:00",
    )
    assert code == 2
    assert out == ""
    assert "--as-of" in err
    assert "--record" in err
    assert store.inserts() == []
    assert env.files() == []


def test_record_accepts_an_as_of_equal_to_the_edge_clock(
    env: _Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _FakeStore()
    code, _, err = _db_run(
        env,
        _FakeFactory(store),
        capsys,
        monkeypatch,
        "--record",
        now=datetime(2027, 4, 1, tzinfo=UTC),
    )
    assert code == 0, err
    assert len(store.kill_gate_ids()) == 1


def test_record_reads_the_clock_once_to_check_an_explicit_as_of(
    env: _Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def counting_clock() -> datetime:
        calls.append(1)
        return RECORD_NOW

    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    code, _, err = _run(
        capsys,
        env.argv("--record"),
        session_factory_fn=_FakeFactory(_FakeStore()).factory_fn,
        now_fn=counting_clock,
    )
    assert code == 0, err
    assert len(calls) == 1


def test_record_failure_keeps_the_files_and_reports_only_the_exception_type(
    env: _Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _FakeStore()
    store.fail_inserts = RuntimeError(f"write failed for {DATABASE_URL}")
    code, out, err = _db_run(env, _FakeFactory(store), capsys, monkeypatch, "--record")
    # WR-05: exit 3 = report produced, record failed (exit 1 promises nothing was written).
    assert code == 3
    assert err.strip() == "Record failed: RuntimeError."
    assert len(_stdout_lines(out)) == 4
    assert len(env.files()) == 2
    _assert_no_secret_anywhere(env, out, err)
