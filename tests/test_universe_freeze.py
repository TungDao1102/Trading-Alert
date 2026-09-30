"""Point-in-time research-universe freeze tool (Phase 13, plan 13-10; D-06..D-09, D039).

No test touches the network or the real manifest. The exchange and the archive
are in-test fakes; every freeze runs on a temporary copy of the DRAFT fixture
manifest and of the gate module, so these tests stay valid after the real freeze
(plan 13-12).
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from binance_sdk_derivatives_trading_usds_futures import BadRequestError, TooManyRequestsError
from scripts.decision_alignment import universe
from src.adapters.binance_usdm import Kline, MarkKline, SymbolFilters
from src.data import universe_freeze as uf
from src.data.archive import ArchiveNotFound

REPO_ROOT = Path(__file__).resolve().parents[1]
DRAFT_FIXTURE = (
    REPO_ROOT / "tests" / "fixtures" / "phase13" / "freeze" / ("research-universe-v1.draft.toml")
)
GATE_SOURCE = REPO_ROOT / "scripts" / "decision_alignment" / "universe.py"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
DAY_MS = 86_400_000
HOUR_MS = 3_600_000

RUN_DATE = date(2026, 9, 30)
DATASET_START = date(2024, 9, 30)
WINDOW_START = date(2024, 8, 31)
_WITNESS_LINE = re.compile(r"^FROZEN_CONTENT_SHA256: str \| None = .*$", re.M)


def _ms(day: date) -> int:
    return (day - date(1970, 1, 1)).days * DAY_MS


def _dt(ms: int) -> datetime:
    return _EPOCH + timedelta(milliseconds=ms)


def _invalid_symbol() -> BadRequestError:
    return BadRequestError(error_message="Invalid symbol.", status_code=-1121)


def _filters(
    symbol: str,
    *,
    status: str = "TRADING",
    contract_type: str = "PERPETUAL",
    quote_asset: str = "USDT",
    onboard_ms: int | None = None,
    delivery_ms: int | None = 4_133_404_800_000,
) -> SymbolFilters:
    return SymbolFilters(
        symbol=symbol,
        contract_type=contract_type,
        status=status,
        onboard_time_utc=None if onboard_ms is None else _dt(onboard_ms),
        price_tick_size=Decimal("0.01"),
        quantity_step_size=Decimal("0.001"),
        min_quantity=Decimal("0.001"),
        max_quantity=None,
        min_notional=Decimal("5"),
        base_asset=symbol.removesuffix(quote_asset),
        quote_asset=quote_asset,
        margin_asset=quote_asset,
        notional_constraints_json="{}",
        order_capabilities_json="{}",
        position_mode_snapshot_json="{}",
        delivery_date_ms=delivery_ms,
    )


def _bar(
    symbol: str, interval: str, open_ms: int, quote_volume: Decimal, trades: int = 10
) -> Kline:
    step = DAY_MS if interval == "1d" else HOUR_MS
    return Kline(
        symbol=symbol,
        interval=interval,
        open_time_utc=_dt(open_ms),
        close_time_utc=_dt(open_ms + step - 1),
        open=Decimal("1"),
        high=Decimal("1"),
        low=Decimal("1"),
        close=Decimal("1"),
        volume=Decimal("1"),
        quote_volume=quote_volume,
        trade_count=trades,
    )


def _daily_bars(
    symbol: str,
    volume: Decimal,
    *,
    days: int = 30,
    zero_trade_day: int | None = None,
    first_day: date = WINDOW_START,
) -> list[Kline]:
    out = []
    for i in range(days):
        trades = 0 if zero_trade_day == i else 10
        out.append(_bar(symbol, "1d", _ms(first_day) + i * DAY_MS, volume, trades))
    return out


class World:
    """Everything the fakes serve: exchangeInfo, REST 1d bars, archive bars."""

    def __init__(self) -> None:
        self.filters: list[SymbolFilters] = []
        self.rest_bars: dict[str, list[Kline]] = {}
        self.rest_errors: dict[tuple[str, str], list[BaseException]] = {}
        self.archive_bars: dict[str, list[Kline]] = {}
        self.archive_errors: dict[str, BaseException] = {}
        self.archive_symbols: list[str] = []
        self.mark_missing: set[str] = set()
        self.calls: list[tuple[str, str, str]] = []

    def add(
        self,
        symbol: str,
        volume: Decimal,
        *,
        listed: bool = True,
        rest: bool = True,
        archive: bool = False,
        **filter_kwargs: Any,
    ) -> None:
        if listed:
            self.filters.append(_filters(symbol, **filter_kwargs))
        if rest:
            self.rest_bars[symbol] = _daily_bars(symbol, volume)
        if archive:
            self.archive_bars[symbol] = _daily_bars(symbol, volume)
            self.archive_symbols.append(symbol)


class FakeAdapter:
    def __init__(self, world: World) -> None:
        self._w = world

    async def exchange_info(self) -> list[SymbolFilters]:
        self._w.calls.append(("exchange_info", "", ""))
        return list(self._w.filters)

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]:
        assert start_ms is not None and end_ms is not None
        self._w.calls.append(("klines", symbol, interval))
        queued = self._w.rest_errors.get((symbol, interval))
        if queued:
            raise queued.pop(0)
        if symbol not in self._w.rest_bars:
            raise _invalid_symbol()
        if interval == "1h":
            return [_bar(symbol, "1h", start_ms, Decimal("1"))][:limit]
        rows = [k for k in self._w.rest_bars[symbol] if start_ms <= _to_ms(k) <= end_ms]
        return rows[:limit]

    async def mark_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[MarkKline]:
        assert start_ms is not None
        self._w.calls.append(("mark_klines", symbol, interval))
        if symbol not in self._w.rest_bars:
            raise _invalid_symbol()
        if symbol in self._w.mark_missing:
            return []
        return [
            MarkKline(
                symbol=symbol,
                interval=interval,
                open_time_utc=_dt(start_ms),
                close_time_utc=_dt(start_ms + HOUR_MS - 1),
                open=Decimal("1"),
                high=Decimal("1"),
                low=Decimal("1"),
                close=Decimal("1"),
                price_tick_count=60,
            )
        ][:limit]


class FakeArchiveSource:
    def __init__(self, world: World) -> None:
        self._w = world

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]:
        assert start_ms is not None and end_ms is not None
        self._w.calls.append(("archive", symbol, interval))
        error = self._w.archive_errors.get(symbol)
        if error is not None:
            raise error
        if symbol not in self._w.archive_bars:
            return []
        if interval == "1h":
            return [_bar(symbol, "1h", start_ms, Decimal("1"))][:limit]
        rows = [k for k in self._w.archive_bars[symbol] if start_ms <= _to_ms(k) < end_ms]
        return rows[:limit]


def _to_ms(bar: Kline) -> int:
    delta = bar.open_time_utc - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1000


@pytest.fixture(autouse=True)
def _fast_and_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(uf, "REST_PACE_SECONDS", 0)

    async def _no_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(uf, "_retry_sleep", _no_sleep)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    w = World()

    async def _list_archive_symbols(client: Any, *, quote: str = "USDT") -> list[str]:
        return list(w.archive_symbols)

    def _source_factory(client: Any, *, search_end_ms: int) -> FakeArchiveSource:
        return FakeArchiveSource(w)

    monkeypatch.setattr(uf, "list_archive_symbols", _list_archive_symbols)
    monkeypatch.setattr(uf, "ArchiveKlineSource", _source_factory)
    return w


def _tracer_world(world: World) -> World:
    """13 TRADING + 2 SETTLING (delivered later) + 1 TRADIFI (excluded) + 1 archive-only."""
    for i in range(1, 14):
        world.add(f"T{i:02d}USDT", Decimal(f"{i * 10}.5"))
    delivered_later = _ms(date(2025, 1, 1))
    world.add("SET1USDT", Decimal("500.5"), status="SETTLING", delivery_ms=delivered_later)
    world.add("SET2USDT", Decimal("5.5"), status="SETTLING", delivery_ms=delivered_later)
    world.add("TFIUSDT", Decimal("9999.5"), contract_type="TRADIFI_PERPETUAL")
    # archive-only: not in exchangeInfo, REST answers -1121, archive serves it
    world.add("ARCHUSDT", Decimal("65.5"), listed=False, rest=False, archive=True)
    # the archive listing also repeats a listed symbol and carries a hostile name
    world.archive_symbols += ["T01USDT", "bad$name"]
    return world


async def _build(world: World, *, top_n: int = 12) -> uf.FreezeReport:
    return await uf.build_freeze_report(
        FakeAdapter(world), object(), run_date=RUN_DATE, top_n=top_n
    )


def _expected_top(world_volumes: dict[str, Decimal], top_n: int = 12) -> list[str]:
    ranked = sorted(world_volumes.items(), key=lambda kv: (-kv[1], kv[0]))
    return sorted(symbol for symbol, _ in ranked[:top_n])


TRACER_VOLUMES: dict[str, Decimal] = {
    **{f"T{i:02d}USDT": Decimal(f"{i * 10}.5") for i in range(1, 14)},
    "SET1USDT": Decimal("500.5"),
    "SET2USDT": Decimal("5.5"),
    "ARCHUSDT": Decimal("65.5"),
}


# ---------------------------------------------------------------- Task 1: tracer


def test_dataset_start_is_two_years_before_run_date() -> None:
    assert uf.dataset_start_for(RUN_DATE) == DATASET_START
    assert uf.dataset_start_for(date(2028, 2, 29)) == date(2026, 2, 28)


def test_discover_candidates_filters_and_dedupes() -> None:
    filters = [
        _filters("AAAUSDT"),
        _filters("BBBUSDT", status="SETTLING"),
        _filters("CCCUSDT", contract_type="TRADIFI_PERPETUAL"),
        _filters("DDDBUSD", quote_asset="BUSD"),
    ]
    found = uf.discover_candidates(
        filters, ["BBBUSDT", "EEEUSDT", "bad$name", "FFFBUSD", "CCCUSDT"]
    )
    assert found == ["AAAUSDT", "BBBUSDT", "EEEUSDT"]


async def test_build_report_ranks_top_12_including_delisted_later(world: World) -> None:
    report = await _build(_tracer_world(world))
    assert report.schema == uf.REPORT_SCHEMA
    assert report.run_date == RUN_DATE
    assert report.dataset_start == DATASET_START
    assert report.window_start == WINDOW_START
    assert report.window_end == DATASET_START
    assert report.top_n == 12
    assert len(report.candidates) == 16
    assert "TFIUSDT" not in {c.symbol for c in report.candidates}
    assert list(report.proposed_symbols) == _expected_top(TRACER_VOLUMES)
    assert "SET1USDT" in report.proposed_symbols  # delisted later, still ranked
    assert "ARCHUSDT" in report.proposed_symbols  # archive-only, still ranked
    assert re.fullmatch(r"[0-9a-f]{64}", report.proposal_sha256)
    top = report.ranked[0]
    assert top[0] == "SET1USDT" and top[1] == Decimal("500.5") * 30


def test_report_round_trips_and_detects_tampering(world: World, tmp_path: Path) -> None:
    import asyncio

    report = asyncio.run(_build(_tracer_world(world)))
    path = tmp_path / "report.json"
    uf.write_report(report, path)
    assert uf.load_report(path) == report
    assert path.read_bytes().endswith(b"\n")

    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["ranked"][0][1] = "1"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(uf.FreezeError, match="proposal_sha256"):
        uf.load_report(path)


def _tmp_witness(tmp_path: Path) -> Path:
    text = GATE_SOURCE.read_text(encoding="utf-8")
    normalised, count = _WITNESS_LINE.subn("FROZEN_CONTENT_SHA256: str | None = None", text)
    assert count == 1
    target = tmp_path / "universe_witness_copy.py"
    target.write_text(normalised, encoding="utf-8", newline="\n")
    return target


def _tmp_manifest(tmp_path: Path) -> Path:
    target = tmp_path / "research-universe-v1.toml"
    shutil.copyfile(DRAFT_FIXTURE, target)
    return target


def _load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("tmp_universe_witness", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_freeze_writes_matching_witnesses(world: World, tmp_path: Path) -> None:
    import asyncio

    report = asyncio.run(_build(_tracer_world(world)))
    report_path = tmp_path / "report.json"
    uf.write_report(report, report_path)
    manifest = _tmp_manifest(tmp_path)
    witness = _tmp_witness(tmp_path)

    digest = uf.freeze(
        report_path,
        approve_sha256=report.proposal_sha256,
        manifest_path=manifest,
        witness_path=witness,
    )

    doc = tomllib.loads(manifest.read_text(encoding="utf-8"))
    assert doc["status"] == "FROZEN"
    assert doc["selection_date"] == "2024-09-30"
    assert doc["symbols"] == list(report.proposed_symbols)
    assert len(doc["symbols"]) == 12
    assert doc["content_sha256"] == digest
    assert universe.validate_manifest(doc) == []
    assert universe.compute_content_sha256(doc) == digest

    assert f'FROZEN_CONTENT_SHA256: str | None = "{digest}"' in witness.read_text(encoding="utf-8")
    module = _load_module(witness)
    assert module.FROZEN_CONTENT_SHA256 == digest
    assert universe.check_second_witness(doc, module.FROZEN_CONTENT_SHA256) == []

    proc = subprocess.run(
        [sys.executable, "-m", "scripts.decision_alignment.universe", str(manifest)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout.strip() == digest


def test_frozen_manifest_preserves_header_comments(world: World, tmp_path: Path) -> None:
    import asyncio

    report = asyncio.run(_build(_tracer_world(world)))
    report_path = tmp_path / "report.json"
    uf.write_report(report, report_path)
    manifest = _tmp_manifest(tmp_path)
    uf.freeze(
        report_path,
        approve_sha256=report.proposal_sha256,
        manifest_path=manifest,
        witness_path=_tmp_witness(tmp_path),
    )
    draft_lines = DRAFT_FIXTURE.read_text(encoding="utf-8").splitlines()
    frozen_lines = manifest.read_text(encoding="utf-8").splitlines()
    dropped = {
        "# State: DRAFT. No symbol is listed on purpose. The volume data needed to rank symbols",
        "# does not exist yet; naming symbols now would be hand-picking, the defect D039 fixes.",
        "# Phase 13 (backfilled dataset) owns the freeze. The live-5 list is a separate config.",
    }
    for line in draft_lines:
        if line.startswith("#") and line not in dropped:
            assert line in frozen_lines, line
    assert any(line.startswith("# State: FROZEN on 2024-09-30") for line in frozen_lines)


# ------------------------------------------------- Task 2: ranking and evidence rules


def _candidate(report: uf.FreezeReport, symbol: str) -> uf.CandidateEvidence:
    return next(c for c in report.candidates if c.symbol == symbol)


def _requests(world: World, symbol: str) -> list[tuple[str, str, str]]:
    return [call for call in world.calls if call[1] == symbol and call[0] != "exchange_info"]


async def test_delivered_before_window_is_ineligible_without_a_request(world: World) -> None:
    world.add("OLDUSDT", Decimal("900.5"), status="SETTLING", delivery_ms=_ms(WINDOW_START) - 1)
    report = await _build(world)
    evidence = _candidate(report, "OLDUSDT")
    assert not evidence.eligible
    assert evidence.reason == uf.DELIVERED_BEFORE_WINDOW
    assert evidence.delivery_date_ms == _ms(WINDOW_START) - 1
    assert evidence.status == "SETTLING"
    assert _requests(world, "OLDUSDT") == []


async def test_listed_after_window_start_is_ineligible_without_a_request(world: World) -> None:
    world.add("NEWUSDT", Decimal("900.5"), onboard_ms=_ms(WINDOW_START) + HOUR_MS)
    report = await _build(world)
    evidence = _candidate(report, "NEWUSDT")
    assert evidence.reason == uf.LISTED_AFTER_WINDOW_START
    assert not evidence.eligible
    assert _requests(world, "NEWUSDT") == []


async def test_incomplete_and_zero_trade_windows_are_ineligible(world: World) -> None:
    world.add("SHORTUSDT", Decimal("10.5"))
    world.rest_bars["SHORTUSDT"] = _daily_bars("SHORTUSDT", Decimal("10.5"), days=29)
    world.add("FLATUSDT", Decimal("10.5"))
    world.rest_bars["FLATUSDT"] = _daily_bars("FLATUSDT", Decimal("10.5"), zero_trade_day=7)
    report = await _build(world)
    short = _candidate(report, "SHORTUSDT")
    assert (short.reason, short.days, short.source) == (uf.INCOMPLETE_WINDOW, 29, "REST")
    assert short.quote_volume_sum is None
    flat = _candidate(report, "FLATUSDT")
    assert (flat.reason, flat.days) == (uf.ZERO_TRADE_DAY, 30)
    assert report.ranked == ()


async def test_rest_invalid_symbol_falls_back_to_archive(world: World) -> None:
    world.add("DELUSDT", Decimal("77.5"), rest=False, archive=True)  # listed, REST says -1121
    report = await _build(world)
    evidence = _candidate(report, "DELUSDT")
    assert evidence.source == "ARCHIVE"
    assert evidence.eligible
    assert evidence.quote_volume_sum == Decimal("77.5") * 30
    assert evidence.quote_volume_mean == Decimal("77.5")


async def test_short_rest_window_tries_archive(world: World) -> None:
    world.add("PARTUSDT", Decimal("40.5"), archive=True)
    world.rest_bars["PARTUSDT"] = _daily_bars("PARTUSDT", Decimal("40.5"), days=29)
    report = await _build(world)
    evidence = _candidate(report, "PARTUSDT")
    assert (evidence.source, evidence.eligible) == ("ARCHIVE", True)


async def test_unavailable_symbol_is_listed_not_dropped(world: World) -> None:
    world.add("GONEUSDT", Decimal("1.5"), rest=False)  # REST -1121, archive has nothing
    world.add("BROKENUSDT", Decimal("1.5"), rest=False)
    world.archive_errors["BROKENUSDT"] = ArchiveNotFound("no file")
    report = await _build(world)
    for symbol in ("GONEUSDT", "BROKENUSDT"):
        evidence = _candidate(report, symbol)
        assert (evidence.reason, evidence.source, evidence.eligible) == (
            uf.UNAVAILABLE,
            "NONE",
            False,
        )
    assert dict(report.unrankable) == {
        "BROKENUSDT": uf.UNAVAILABLE,
        "GONEUSDT": uf.UNAVAILABLE,
    }
    assert "GONEUSDT" not in report.proposed_symbols


async def test_rate_limit_is_retried_and_never_switches_source(world: World) -> None:
    world.add("SLOWUSDT", Decimal("12.5"), archive=True)
    limited = TooManyRequestsError(error_message="slow down", status_code=429)
    world.rest_errors[("SLOWUSDT", "1d")] = [limited, limited]
    report = await _build(world)
    assert _candidate(report, "SLOWUSDT").source == "REST"
    day_calls = [c for c in world.calls if c[:2] == ("klines", "SLOWUSDT") and c[2] == "1d"]
    assert len(day_calls) == 3
    assert not [c for c in world.calls if c[0] == "archive" and c[1] == "SLOWUSDT"]


async def test_exhausted_rate_limit_fails_the_run(world: World) -> None:
    world.add("SLOWUSDT", Decimal("12.5"), archive=True)
    limited = TooManyRequestsError(error_message="slow down", status_code=429)
    world.rest_errors[("SLOWUSDT", "1d")] = [limited] * 20
    with pytest.raises(TooManyRequestsError):
        await _build(world)
    assert not [c for c in world.calls if c[0] == "archive" and c[1] == "SLOWUSDT"]


async def test_equal_sums_at_the_cut_are_ordered_by_symbol(world: World) -> None:
    world.add("AAAUSDT", Decimal("100.5"))
    world.add("CCCUSDT", Decimal("50.5"))
    world.add("BBBUSDT", Decimal("50.5"))
    report = await _build(world, top_n=2)
    assert [symbol for symbol, _ in report.ranked] == ["AAAUSDT", "BBBUSDT", "CCCUSDT"]
    assert report.proposed_symbols == ("AAAUSDT", "BBBUSDT")


async def test_availability_records_trade_and_mark_per_proposed_symbol(world: World) -> None:
    world.add("RESTUSDT", Decimal("30.5"))
    world.add("ARCHUSDT", Decimal("20.5"), listed=False, rest=False, archive=True)
    world.add("NOMARKUSDT", Decimal("10.5"))
    world.mark_missing.add("NOMARKUSDT")
    report = await _build(world)
    assert report.availability == (
        ("ARCHUSDT", "ARCHIVE", "UNAVAILABLE"),
        ("NOMARKUSDT", "REST", "UNAVAILABLE"),
        ("RESTUSDT", "REST", "REST"),
    )
    assert report.proposed_symbols == ("ARCHUSDT", "NOMARKUSDT", "RESTUSDT")  # never re-ranked


async def test_fewer_eligible_than_top_n_reports_short_and_freeze_refuses(
    world: World, tmp_path: Path
) -> None:
    for i in range(5):
        world.add(f"S{i}USDT", Decimal(f"{i + 1}0.5"))
    report = await _build(world)
    assert len(report.proposed_symbols) == 5
    report_path = tmp_path / "report.json"
    uf.write_report(report, report_path)
    manifest = _tmp_manifest(tmp_path)
    witness = _tmp_witness(tmp_path)
    before = (manifest.read_bytes(), witness.read_bytes())
    with pytest.raises(uf.FreezeError, match="does not validate"):
        uf.freeze(
            report_path,
            approve_sha256=report.proposal_sha256,
            manifest_path=manifest,
            witness_path=witness,
        )
    assert (manifest.read_bytes(), witness.read_bytes()) == before


def test_freeze_report_is_byte_deterministic(world: World, tmp_path: Path) -> None:
    import asyncio

    _tracer_world(world)
    first = asyncio.run(_build(world))
    second = asyncio.run(_build(world))
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    uf.write_report(first, a)
    uf.write_report(second, b)
    assert a.read_bytes() == b.read_bytes()
    assert first.proposal_sha256 == second.proposal_sha256


def test_module_has_no_float_call_or_annotation() -> None:
    import ast

    tree = ast.parse(Path(uf.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "float"
        if isinstance(node, ast.AnnAssign) and isinstance(node.annotation, ast.Name):
            assert node.annotation.id != "float"


# ---------------------------------------- Task 3: freeze safety gates and the CLI


class _Setup:
    def __init__(self, tmp_path: Path, report: uf.FreezeReport) -> None:
        self.report = report
        self.report_path = tmp_path / "report.json"
        uf.write_report(report, self.report_path)
        self.manifest = _tmp_manifest(tmp_path)
        self.witness = _tmp_witness(tmp_path)

    def argv(self, *, approve: str | None = None, freeze: bool = False) -> list[str]:
        argv = [
            "freeze",
            "--report",
            str(self.report_path),
            "--approve",
            self.report.proposal_sha256 if approve is None else approve,
            "--manifest",
            str(self.manifest),
            "--witness",
            str(self.witness),
        ]
        return [*argv, "--freeze"] if freeze else argv

    def snapshot(self) -> tuple[bytes, bytes]:
        return self.manifest.read_bytes(), self.witness.read_bytes()


@pytest.fixture
def setup(world: World, tmp_path: Path) -> _Setup:
    import asyncio

    report = asyncio.run(_build(_tracer_world(world)))
    return _Setup(tmp_path, report)


def test_freeze_without_flag_writes_nothing(
    setup: _Setup, capsys: pytest.CaptureFixture[str]
) -> None:
    before = setup.snapshot()
    assert uf.main(setup.argv()) == 0
    assert setup.snapshot() == before
    out = capsys.readouterr().out
    assert 'status = "FROZEN"' in out
    assert re.search(r"content_sha256: [0-9a-f]{64}", out)
    assert "SET1USDT" in out


def test_wrong_approval_hash_refuses(setup: _Setup, capsys: pytest.CaptureFixture[str]) -> None:
    before = setup.snapshot()
    for freeze_flag in (False, True):
        assert uf.main(setup.argv(approve="0" * 64, freeze=freeze_flag)) == 2
        assert "approval hash does not match" in capsys.readouterr().err
        assert setup.snapshot() == before


def test_edited_report_refuses_even_with_its_old_hash(setup: _Setup) -> None:
    doc = json.loads(setup.report_path.read_text(encoding="utf-8"))
    doc["proposed_symbols"][0] = "ZZZUSDT"
    setup.report_path.write_text(json.dumps(doc), encoding="utf-8")
    before = setup.snapshot()
    assert uf.main(setup.argv(freeze=True)) == 2
    assert setup.snapshot() == before


def test_refreeze_refuses(setup: _Setup, capsys: pytest.CaptureFixture[str]) -> None:
    assert uf.main(setup.argv(freeze=True)) == 0
    frozen = setup.snapshot()
    capsys.readouterr()
    assert uf.main(setup.argv(freeze=True)) == 2
    assert "only DRAFT can be frozen" in capsys.readouterr().err
    assert setup.snapshot() == frozen


def test_already_set_witness_refuses(setup: _Setup, capsys: pytest.CaptureFixture[str]) -> None:
    text = setup.witness.read_text(encoding="utf-8")
    setup.witness.write_text(
        text.replace(
            "FROZEN_CONTENT_SHA256: str | None = None",
            f'FROZEN_CONTENT_SHA256: str | None = "{"a" * 64}"',
        ),
        encoding="utf-8",
        newline="\n",
    )
    before = setup.snapshot()
    assert uf.main(setup.argv(freeze=True)) == 2
    assert "already set" in capsys.readouterr().err
    assert setup.snapshot() == before


def test_witness_write_failure_restores_the_manifest(
    setup: _Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = setup.snapshot()
    real_replace = uf.os.replace

    def _failing(src: Any, dst: Any) -> None:
        if Path(dst) == setup.witness:
            raise OSError("disk full")
        real_replace(src, dst)

    monkeypatch.setattr(uf.os, "replace", _failing)
    assert uf.main(setup.argv(freeze=True)) != 0
    assert setup.snapshot() == before
    assert not list(setup.manifest.parent.glob("*.tmp"))


class _FakeClient:
    async def aclose(self) -> None:
        return None


def _patch_factories(monkeypatch: pytest.MonkeyPatch, world: World) -> None:
    monkeypatch.setattr(uf, "_make_adapter", lambda: FakeAdapter(world))
    monkeypatch.setattr(uf, "_make_archive_client", lambda: _FakeClient())


def test_propose_writes_report_and_prints_the_review_block(
    world: World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _tracer_world(world)
    world.add("GONEUSDT", Decimal("1.5"), rest=False)
    world.mark_missing.add("SET1USDT")
    _patch_factories(monkeypatch, world)
    out_path = tmp_path / "report.json"
    assert uf.main(["propose", "--run-date", "2026-09-30", "--out", str(out_path)]) == 0
    report = uf.load_report(out_path)
    out = capsys.readouterr().out
    assert "dataset_start=2024-09-30" in out
    assert f"proposal_sha256: {report.proposal_sha256}" in out
    assert " ".join(report.proposed_symbols) in out
    assert "GONEUSDT" in out  # unrankable list
    assert "UNAVAILABLE proposed data: ARCHUSDT SET1USDT" in out


def test_propose_exits_3_when_too_few_symbols_are_eligible(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for i in range(5):
        world.add(f"S{i}USDT", Decimal(f"{i + 1}0.5"))
    _patch_factories(monkeypatch, world)
    out_path = tmp_path / "report.json"
    assert uf.main(["propose", "--run-date", "2026-09-30", "--out", str(out_path)]) == 3
    assert len(uf.load_report(out_path).proposed_symbols) == 5  # report still written


def test_freeze_requires_report_and_approve() -> None:
    with pytest.raises(SystemExit) as info:
        uf.main(["freeze", "--report", "x.json"])
    assert info.value.code == 2


def test_cli_help_lists_both_subcommands() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "src.data.universe_freeze", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "propose" in proc.stdout
    assert "freeze" in proc.stdout
