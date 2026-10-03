"""Tests for the OI/funding collect list loader (Phase 13, plan 01, DATA-02).

The collect list is the operational input naming which symbols the
collector polls (D-01, D-02). The loader fails closed: any defect raises
`CollectListError` and the collector never falls back to the live-5.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from src.data.backfill import LIVE_5
from src.data.collect_list import (
    DEFAULT_COLLECT_LIST_PATH,
    CollectList,
    CollectListError,
    load_collect_list,
    propose_collect_list,
    reissue_collect_list,
    render_collect_list_toml,
)
from src.data.collect_list import main as collect_list_main
from src.data.universe_freeze import (
    REPORT_SCHEMA,
    CandidateEvidence,
    FreezeError,
    FreezeReport,
    _hash_report,
    write_report,
)

EXTRA_SYMBOLS = (
    "ADAUSDT",
    "AVAXUSDT",
    "DOGEUSDT",
    "DOTUSDT",
    "LINKUSDT",
    "LTCUSDT",
    "MATICUSDT",
    "NEARUSDT",
    "SUIUSDT",
    "TRXUSDT",
    "UNIUSDT",
)


def _render(
    *,
    symbols: list[str] | None = None,
    schema: str = "collect-list/1",
    chosen_on: str = "2026-09-30",
    top_n: str = "15",
    drop: tuple[str, ...] = (),
    raw_symbols: str | None = None,
) -> str:
    syms = list(LIVE_5) + list(EXTRA_SYMBOLS) if symbols is None else symbols
    if raw_symbols is None:
        raw_symbols = "[" + ", ".join(f'"{s}"' for s in syms) + "]"
    fields = {
        "schema": f'"{schema}"',
        "list_id": '"collect-list-v1"',
        "chosen_on": f'"{chosen_on}"',
        "selection_rule": '"live-5 union top 15 by 24h quoteVolume"',
        "top_n": top_n,
        "symbols": raw_symbols,
    }
    return "\n".join(f"{k} = {v}" for k, v in fields.items() if k not in drop) + "\n"


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "collect-list.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_valid_list_sorted(tmp_path: Path) -> None:
    path = _write(tmp_path, _render())
    cl = load_collect_list(path)
    assert isinstance(cl, CollectList)
    assert cl.list_id == "collect-list-v1"
    assert cl.chosen_on == date(2026, 9, 30)
    assert cl.top_n == 15
    assert cl.selection_rule
    assert len(cl.symbols) == 16
    assert list(cl.symbols) == sorted(cl.symbols)
    assert set(LIVE_5) <= set(cl.symbols)


def test_default_path_is_operational_docs_location() -> None:
    assert DEFAULT_COLLECT_LIST_PATH == (
        Path("docs") / "research" / "universe" / "collect-list-v2.toml"
    )


def test_missing_file_names_path(tmp_path: Path) -> None:
    missing = tmp_path / "nope.toml"
    with pytest.raises(CollectListError, match="nope.toml"):
        load_collect_list(missing)


def test_invalid_toml_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "this is = = not toml [")
    with pytest.raises(CollectListError, match="collect-list.toml"):
        load_collect_list(path)


def test_collect_list_error_is_value_error() -> None:
    assert issubclass(CollectListError, ValueError)


@pytest.mark.parametrize(
    "key",
    ["schema", "list_id", "chosen_on", "selection_rule", "top_n", "symbols"],
)
def test_missing_key_is_rejected(tmp_path: Path, key: str) -> None:
    path = _write(tmp_path, _render(drop=(key,)))
    with pytest.raises(CollectListError, match=key):
        load_collect_list(path)


def test_wrong_schema_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, _render(schema="collect-list/2"))
    with pytest.raises(CollectListError, match="schema"):
        load_collect_list(path)


def test_empty_collect_list_is_rejected(tmp_path: Path) -> None:
    """D-20: an empty list must never silently mean 'collect nothing'."""
    path = _write(tmp_path, _render(symbols=[]))
    with pytest.raises(CollectListError, match="collect-list.toml"):
        load_collect_list(path)


@pytest.mark.parametrize("bad", ["btcusdt", "BTC-USDT", "../BTCUSDT", "BTCUSDC", "BTCUSDT/", ""])
def test_malformed_symbol_is_rejected(tmp_path: Path, bad: str) -> None:
    symbols = [*LIVE_5, bad]
    path = _write(tmp_path, _render(symbols=symbols))
    with pytest.raises(CollectListError, match="symbol"):
        load_collect_list(path)


def test_non_string_symbol_is_rejected(tmp_path: Path) -> None:
    raw = "[" + ", ".join(f'"{s}"' for s in LIVE_5) + ", 42]"
    path = _write(tmp_path, _render(raw_symbols=raw))
    with pytest.raises(CollectListError, match="symbol"):
        load_collect_list(path)


def test_duplicate_symbol_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, _render(symbols=[*LIVE_5, "ADAUSDT", "ADAUSDT"]))
    with pytest.raises(CollectListError, match="duplicate"):
        load_collect_list(path)


@pytest.mark.parametrize("missing", list(LIVE_5))
def test_missing_live5_symbol_is_rejected(tmp_path: Path, missing: str) -> None:
    symbols = [s for s in [*LIVE_5, *EXTRA_SYMBOLS] if s != missing]
    path = _write(tmp_path, _render(symbols=symbols))
    with pytest.raises(CollectListError, match=missing):
        load_collect_list(path)


@pytest.mark.parametrize("bad_date", ["2026-9-30", "2026-02-30", "30-09-2026", ""])
def test_bad_chosen_on_is_rejected(tmp_path: Path, bad_date: str) -> None:
    path = _write(tmp_path, _render(chosen_on=bad_date))
    with pytest.raises(CollectListError, match="chosen_on"):
        load_collect_list(path)


@pytest.mark.parametrize("bad_top_n", ["0", "-3", "true", '"15"', "1.5"])
def test_bad_top_n_is_rejected(tmp_path: Path, bad_top_n: str) -> None:
    path = _write(tmp_path, _render(top_n=bad_top_n))
    with pytest.raises(CollectListError, match="top_n"):
        load_collect_list(path)


# --------------------------------------------------------------------------- #
# Task 2: deterministic proposer, renderer, CLI, committed file, packaging.
# --------------------------------------------------------------------------- #

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "phase13" / "collect_list"
REPO_ROOT = Path(__file__).resolve().parents[1]
CHOSEN_ON = date(2026, 9, 30)


def _fixture_inputs() -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    ticker = json.loads((FIXTURE_DIR / "ticker_24hr.json").read_text(encoding="utf-8"))
    exchange = json.loads((FIXTURE_DIR / "exchange_info.json").read_text(encoding="utf-8"))
    return ticker, exchange["symbols"]


def _propose(
    ticker: list[dict[str, str]] | None = None,
    symbols: list[dict[str, object]] | None = None,
    **overrides: object,
) -> CollectList:
    fixture_ticker, fixture_symbols = _fixture_inputs()
    kwargs: dict[str, object] = {
        "live_symbols": LIVE_5,
        "top_n": 15,
        "chosen_on": CHOSEN_ON,
        "list_id": "collect-list-v1",
    }
    kwargs.update(overrides)
    return propose_collect_list(
        fixture_ticker if ticker is None else ticker,
        fixture_symbols if symbols is None else symbols,
        **kwargs,  # type: ignore[arg-type]
    )


def test_proposer_excludes_non_trading_non_perpetual_non_usdt() -> None:
    cl = _propose()
    excluded = {
        "XAUUSDT",  # TRADIFI_PERPETUAL
        "OMGUSDT",  # SETTLING
        "GAIBUSDT",  # PENDING_TRADING
        "BTCUSDT_261225",  # CURRENT_QUARTER
        "BTCUSDC",  # USDC quote
    }
    assert excluded.isdisjoint(cl.symbols)


def test_proposer_union_of_top15_and_live5_with_symbol_tiebreak() -> None:
    cl = _propose()
    assert cl.chosen_on == CHOSEN_ON
    assert cl.top_n == 15
    assert cl.list_id == "collect-list-v1"
    # AAVEUSDT and UNIUSDT tie at the cut; symbol ascending picks AAVEUSDT.
    assert "AAVEUSDT" in cl.symbols
    assert "UNIUSDT" not in cl.symbols
    # BNBUSDT (live-5) ranks below the top 15 in the fixture but is included.
    assert "BNBUSDT" in cl.symbols
    assert set(LIVE_5) <= set(cl.symbols)
    assert list(cl.symbols) == sorted(cl.symbols)
    assert len(cl.symbols) == 16
    assert cl.symbols == (
        "AAVEUSDT",
        "BNBUSDT",
        "BTCUSDT",
        "DOGEUSDT",
        "ENAUSDT",
        "ETHUSDT",
        "HYPEUSDT",
        "MOVRUSDT",
        "NEARUSDT",
        "PUMPUSDT",
        "QNTUSDT",
        "SOLUSDT",
        "SUIUSDT",
        "WLDUSDT",
        "XRPUSDT",
        "ZECUSDT",
    )


def test_proposer_is_deterministic_under_input_order() -> None:
    ticker, symbols = _fixture_inputs()
    first = _propose(ticker, symbols)
    second = _propose(list(reversed(ticker)), list(reversed(symbols)))
    assert first == second
    assert render_collect_list_toml(first, source_note="x") == render_collect_list_toml(
        second, source_note="x"
    )


def test_proposer_compares_volumes_as_decimals_not_strings() -> None:
    ticker, symbols = _fixture_inputs()
    rows = [dict(r) for r in ticker]
    for row in rows:
        if row["symbol"] == "HBARUSDT":
            row["quoteVolume"] = "9E+12"  # lexicographically small, numerically huge
    cl = _propose(rows, symbols)
    assert "HBARUSDT" in cl.symbols


@pytest.mark.parametrize("bad", ["abc", "NaN", "Infinity", "-Infinity", ""])
def test_proposer_rejects_non_decimal_quote_volume(bad: str) -> None:
    ticker, symbols = _fixture_inputs()
    rows = [dict(r) for r in ticker]
    for row in rows:
        if row["symbol"] == "ETHUSDT":
            row["quoteVolume"] = bad
    with pytest.raises(CollectListError, match="quoteVolume"):
        _propose(rows, symbols)


def test_proposer_rejects_live_symbol_missing_from_exchange_info() -> None:
    ticker, symbols = _fixture_inputs()
    trimmed = [s for s in symbols if s["symbol"] != "BNBUSDT"]
    with pytest.raises(CollectListError, match="BNBUSDT"):
        _propose(ticker, trimmed)


def test_proposer_rejects_live_symbol_not_trading() -> None:
    ticker, symbols = _fixture_inputs()
    mutated = [dict(s) for s in symbols]
    for rec in mutated:
        if rec["symbol"] == "SOLUSDT":
            rec["status"] = "SETTLING"
    with pytest.raises(CollectListError, match="SOLUSDT"):
        _propose(ticker, mutated)


def test_proposer_rejects_fewer_eligible_than_top_n() -> None:
    with pytest.raises(CollectListError, match="eligible"):
        _propose(top_n=500)


def test_render_round_trips_through_loader(tmp_path: Path) -> None:
    cl = _propose()
    text = render_collect_list_toml(cl, source_note="fixture run\nsecond line")
    path = _write(tmp_path, text)
    assert load_collect_list(path) == cl
    assert "operational input" in text
    assert "FROZEN" in text
    assert "research-universe" in text
    assert "fixture run" in text and "second line" in text
    keys = [
        line.split(" =")[0]
        for line in text.splitlines()
        if line and not line.startswith(("#", " ", "]"))
    ]
    assert keys == [
        "schema",
        "list_id",
        "chosen_on",
        "selection_rule",
        "top_n",
        "symbols",
    ]


def _cli_args(tmp_path: Path, out: Path) -> list[str]:
    return [
        "propose",
        "--ticker-json",
        str(FIXTURE_DIR / "ticker_24hr.json"),
        "--exchange-info-json",
        str(FIXTURE_DIR / "exchange_info.json"),
        "--chosen-on",
        "2026-09-30",
        "--out",
        str(out),
    ]


def test_cli_propose_writes_loadable_file(tmp_path: Path) -> None:
    out = tmp_path / "list.toml"
    assert collect_list_main(_cli_args(tmp_path, out)) == 0
    assert load_collect_list(out) == _propose()


def test_cli_propose_refuses_to_overwrite_existing_out(tmp_path: Path) -> None:
    out = tmp_path / "list.toml"
    out.write_text("keep me", encoding="utf-8")
    assert collect_list_main(_cli_args(tmp_path, out)) == 2
    assert out.read_text(encoding="utf-8") == "keep me"


def test_cli_propose_bad_chosen_on_exits_2(tmp_path: Path) -> None:
    out = tmp_path / "list.toml"
    args = _cli_args(tmp_path, out)
    args[args.index("2026-09-30")] = "2026-02-30"
    assert collect_list_main(args) == 2
    assert not out.exists()


def test_committed_collect_list_is_valid_live5_superset() -> None:
    path = REPO_ROOT / DEFAULT_COLLECT_LIST_PATH
    cl = load_collect_list(path)
    assert set(LIVE_5) <= set(cl.symbols)
    assert 15 <= len(cl.symbols) <= 20
    assert cl.chosen_on <= datetime.now(UTC).date()
    # The default (v2) is derived from v1, whose source note names the public endpoints.
    v1_text = (REPO_ROOT / "docs" / "research" / "universe" / "collect-list-v1.toml").read_text(
        encoding="utf-8"
    )
    assert "GET /fapi/v1/ticker/24hr" in v1_text
    assert "GET /fapi/v1/exchangeInfo" in v1_text
    assert "freeze-report.json" in path.read_text(encoding="utf-8")


def test_dockerfile_copies_universe_directory() -> None:
    lines = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()
    copy_line = "COPY docs/research/universe ./docs/research/universe"
    assert lines.count(copy_line) == 1
    useradd = next(i for i, ln in enumerate(lines) if ln.startswith("RUN useradd"))
    assert lines.index(copy_line) < useradd


# --------------------------------------------------------------------------- #
# 13-13 Task 1: re-issue the collect list after the research-universe freeze (D-24).
# --------------------------------------------------------------------------- #


def _candidate(symbol: str, status: str) -> CandidateEvidence:
    return CandidateEvidence(
        symbol=symbol,
        status=status,
        contract_type="PERPETUAL",
        onboard_utc=None,
        delivery_date_ms=None,
        source="exchangeInfo",
        days=30,
        quote_volume_sum=None,
        quote_volume_mean=None,
        eligible=True,
        reason="ok",
    )


def _write_freeze_report(path: Path, proposed: dict[str, str]) -> Path:
    """Write a hash-valid freeze report whose proposal carries `proposed` symbol: status."""
    unsigned = FreezeReport(
        schema=REPORT_SCHEMA,
        run_date=date(2026, 10, 3),
        dataset_start=date(2025, 10, 3),
        window_start=date(2025, 9, 3),
        window_end=date(2025, 10, 3),
        top_n=len(proposed),
        candidates=tuple(_candidate(sym, status) for sym, status in sorted(proposed.items())),
        ranked=(),
        proposed_symbols=tuple(sorted(proposed)),
        unrankable=(),
        availability=(),
        proposal_sha256="",
    )
    report = FreezeReport(**{**unsigned.__dict__, "proposal_sha256": _hash_report(unsigned)})
    write_report(report, path)
    return path


def _base_list(tmp_path: Path) -> CollectList:
    return load_collect_list(_write(tmp_path, _render()))


def test_reissue_adds_only_trading_frozen_symbols(tmp_path: Path) -> None:
    base = _base_list(tmp_path)
    report = _write_freeze_report(
        tmp_path / "freeze.json",
        {"NEWAUSDT": "TRADING", "NEWBUSDT": "SETTLING", "ADAUSDT": "TRADING"},
    )
    result = reissue_collect_list(
        base, report, chosen_on=date(2026, 10, 3), list_id="collect-list-v2"
    )
    assert set(result.symbols) == set(base.symbols) | {"NEWAUSDT"}
    assert "NEWBUSDT" not in result.symbols
    assert result.symbols.count("ADAUSDT") == 1
    assert list(result.symbols) == sorted(result.symbols)
    assert result.list_id == "collect-list-v2"
    assert result.chosen_on == date(2026, 10, 3)
    assert result.top_n == base.top_n
    assert "D-24" in result.selection_rule
    assert "TRADING" in result.selection_rule


def test_reissue_is_superset_of_base_and_live5(tmp_path: Path) -> None:
    base = _base_list(tmp_path)
    report = _write_freeze_report(tmp_path / "freeze.json", {"NEWAUSDT": "TRADING"})
    result = reissue_collect_list(
        base, report, chosen_on=date(2026, 10, 3), list_id="collect-list-v2"
    )
    assert set(base.symbols) <= set(result.symbols)
    assert set(LIVE_5) <= set(result.symbols)
    # A report edited after its hash was computed must not be trusted.
    text = report.read_text(encoding="utf-8").replace("NEWAUSDT", "EVILUSDT")
    report.write_text(text, encoding="utf-8")
    with pytest.raises(FreezeError):
        reissue_collect_list(base, report, chosen_on=date(2026, 10, 3), list_id="collect-list-v2")


def test_reissue_cli_refuses_overwrite(tmp_path: Path) -> None:
    base_path = _write(tmp_path, _render())
    report = _write_freeze_report(tmp_path / "freeze.json", {"NEWAUSDT": "TRADING"})
    out = tmp_path / "v2.toml"
    args = [
        "reissue",
        "--base",
        str(base_path),
        "--freeze-report",
        str(report),
        "--chosen-on",
        "2026-10-03",
        "--out",
        str(out),
    ]
    assert collect_list_main(args) == 0
    written = load_collect_list(out)
    assert "NEWAUSDT" in written.symbols
    assert written.list_id == "collect-list-v2"
    text = out.read_text(encoding="utf-8")
    assert base_path.as_posix() in text and report.as_posix() in text
    assert collect_list_main(args) == 2
    assert out.read_text(encoding="utf-8") == text


def test_default_collect_list_is_v2_and_loads() -> None:
    assert DEFAULT_COLLECT_LIST_PATH.name == "collect-list-v2.toml"
    v1 = load_collect_list(REPO_ROOT / "docs" / "research" / "universe" / "collect-list-v1.toml")
    v2 = load_collect_list(REPO_ROOT / DEFAULT_COLLECT_LIST_PATH)
    assert v2.list_id == "collect-list-v2"
    assert set(v1.symbols) <= set(v2.symbols)
    assert set(LIVE_5) <= set(v2.symbols)


def test_collector_import_chain_does_not_load_scripts_or_universe_freeze() -> None:
    """WR-05: the collector entrypoint must not depend on `scripts/` or the freeze tool."""
    import subprocess
    import sys
    from pathlib import Path

    code = (
        "import sys\n"
        "import src.data.collect_list, src.data.collector\n"
        "bad = [m for m in sys.modules if m == 'scripts' or m.startswith('scripts.')"
        " or m == 'src.data.universe_freeze']\n"
        "sys.exit(1 if bad else 0)\n"
    )
    repo_root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
