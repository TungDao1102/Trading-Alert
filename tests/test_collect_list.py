"""Tests for the OI/funding collect list loader (Phase 13, plan 01, DATA-02).

The collect list is the operational input naming which symbols the
collector polls (D-01, D-02). The loader fails closed: any defect raises
`CollectListError` and the collector never falls back to the live-5.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from src.data.backfill import LIVE_5
from src.data.collect_list import (
    DEFAULT_COLLECT_LIST_PATH,
    CollectList,
    CollectListError,
    load_collect_list,
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
        Path("docs") / "research" / "universe" / "collect-list-v1.toml"
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


@pytest.mark.parametrize(
    "bad", ["btcusdt", "BTC-USDT", "../BTCUSDT", "BTCUSDC", "BTCUSDT/", ""]
)
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
