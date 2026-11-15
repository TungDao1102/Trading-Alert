"""The Phase 21 recorded-Demo fixtures are generated, secret-free and reproducible (plan 21-03).

`scripts/gen_phase21_fixtures.py` unflattens the owner-run Demo capture of 2026-10-22 into the
SDK wire shape. Demo values: demo-observed, not mainnet. Nothing here is typed by hand.
Plan 21-08 adds the REST trade rows, the empty funding income answer and the recorded stream
frames (byte-for-byte copies).
"""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATOR_PATH = REPO_ROOT / "scripts" / "gen_phase21_fixtures.py"
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "phase21"
RECORDED = FIXTURE_ROOT / "recorded_demo"
FRAMES = RECORDED / "frames"
PHASE19_FIXTURES = (
    REPO_ROOT
    / ".planning"
    / "phases"
    / "19-execution-plan-binding-price-check"
    / "evidence"
    / "fixtures"
)
JSON_FIXTURES = [
    "account_balance_v3.json",
    "account_config.json",
    "account_information_v3.json",
    "income_funding_empty.json",
    "user_trades_commission_case.json",
    "user_trades_triggered_bracket.json",
]


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_phase21_fixtures", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)).replace("\\", "/"): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _walk_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key))
            keys |= _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            keys |= _walk_keys(item)
    return keys


def test_generator_rerun_is_byte_identical(tmp_path: Path) -> None:
    generator = _load_generator()
    first, second = tmp_path / "first", tmp_path / "second"
    assert generator.main(["--out", str(first)]) == 0
    assert generator.main(["--out", str(second)]) == 0
    assert _snapshot(first) == _snapshot(second)
    assert _snapshot(first)  # something was written
    # Frames are copied byte for byte from the capture files, which a Windows checkout
    # turns into CRLF; only the files the generator renders itself must be LF.
    rendered = {k: v for k, v in _snapshot(first).items() if "/frames/" not in k}
    assert rendered
    assert all(b"\r" not in data for data in rendered.values())


def test_committed_account_information_equals_a_fresh_run(tmp_path: Path) -> None:
    generator = _load_generator()
    assert generator.main(["--out", str(tmp_path)]) == 0
    fresh = _json(tmp_path / "recorded_demo" / "account_information_v3.json")
    assert _json(RECORDED / "account_information_v3.json") == fresh


def test_the_generator_imports_nothing_from_src_or_tests() -> None:
    tree = ast.parse(GENERATOR_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint({"src", "tests", "binance_sdk_derivatives_trading_usds_futures"})


def test_recorded_demo_account_information_carries_the_capture_values() -> None:
    data = _json(RECORDED / "account_information_v3.json")
    assert data["totalMarginBalance"] == "4999.09343961"
    assert data["totalWalletBalance"] == "4999.09343961"
    assert data["totalUnrealizedProfit"] == "0.00000000"
    by_asset = {row["asset"]: row for row in data["assets"]}
    assert by_asset["USDT"]["marginBalance"] == "4999.09343961"
    assert by_asset["USDC"]["walletBalance"] == "5000.00000000"
    assert by_asset["BTC"]["walletBalance"] == "0.01000000"
    assert isinstance(by_asset["USDT"]["updateTime"], int)  # WIRE_TYPES gave it its JSON type


def test_unflatten_builds_lists_and_converts_wire_types() -> None:
    generator = _load_generator()
    mixed = generator.unflatten_summary(
        {"total": "1.50", "assets.1.asset": "B", "assets.0.asset": "A"}
    )
    assert mixed == {"total": "1.50", "assets": [{"asset": "A"}, {"asset": "B"}]}
    rows = generator.unflatten_summary({"1.asset": "B", "0.asset": "A", "0.updateTime": "12"})
    assert rows == [{"asset": "A", "updateTime": 12}, {"asset": "B"}]


def test_unflatten_rejects_a_gap_in_the_list_indices() -> None:
    generator = _load_generator()
    with pytest.raises(ValueError, match="gap"):
        generator.unflatten_summary({"0.asset": "A", "2.asset": "C"})


@pytest.mark.parametrize(
    ("field", "text"),
    [("updateTime", "abc"), ("updateTime", "1.5"), ("dualSidePosition", "yes"), ("canTrade", "1")],
)
def test_a_non_string_wire_field_with_foreign_text_raises(field: str, text: str) -> None:
    generator = _load_generator()
    with pytest.raises(ValueError, match=field):
        generator.unflatten_summary({field: text})


def test_the_alias_key_is_dropped_by_the_generator() -> None:
    generator = _load_generator()
    rows = generator.unflatten_summary(
        {f"0.{generator.ALIAS_FIELD}": "x", "0.asset": "USDT", "0.balance": "1.0"}
    )
    assert rows == [{"asset": "USDT", "balance": "1.0"}]


def test_every_generated_file_is_present_and_equals_a_fresh_run(tmp_path: Path) -> None:
    generator = _load_generator()
    assert generator.main(["--out", str(tmp_path)]) == 0
    fresh = {path.name: _json(path) for path in sorted((tmp_path / "recorded_demo").glob("*.json"))}
    assert sorted(fresh) == JSON_FIXTURES
    for name, value in fresh.items():
        assert _json(RECORDED / name) == value
    assert sorted(path.name for path in RECORDED.glob("*.json")) == sorted(fresh)


def test_no_fixture_carries_the_account_alias_key_at_any_depth() -> None:
    generator = _load_generator()
    files = sorted(RECORDED.glob("*.json")) + sorted(FRAMES.glob("*.json"))
    assert len(list(RECORDED.glob("*.json"))) == len(JSON_FIXTURES)
    for path in files:
        assert generator.ALIAS_FIELD not in _walk_keys(_json(path)), path.name
        assert generator.ALIAS_FIELD not in path.read_text(encoding="utf-8")


def test_recorded_demo_balance_rows_and_config_flags_carry_the_capture_values() -> None:
    rows = {row["asset"]: row for row in _json(RECORDED / "account_balance_v3.json")}
    assert rows["USDT"]["balance"] == "4999.09343961"
    assert rows["USDT"]["crossUnPnl"] == "0.00000000"
    assert rows["USDC"]["balance"] == "5000.00000000"
    assert rows["BTC"]["balance"] == "0.01000000"
    assert rows["USDT"]["marginAvailable"] is True
    config = _json(RECORDED / "account_config.json")
    assert config["multiAssetsMargin"] is False
    assert config["dualSidePosition"] is False
    assert config["feeTier"] == 0
    assert config["tradeGroupId"] == -1


def test_the_readme_lists_every_generated_fixture_with_the_recorded_demo_label() -> None:
    readme = (FIXTURE_ROOT / "README.md").read_text(encoding="utf-8")
    for path in sorted(RECORDED.glob("*.json")):
        assert f"`recorded_demo/{path.name}`" in readme
    for path in sorted(FRAMES.glob("*.json")):
        assert f"`recorded_demo/frames/{path.name}`" in readme
    assert readme.count("RECORDED_DEMO") >= 4
    assert "not mainnet" in readme


# ---------------------------------------------------- plan 21-08: trades, income, frames


def test_the_triggered_bracket_trade_row_is_the_recorded_demo_close() -> None:
    rows = _json(RECORDED / "user_trades_triggered_bracket.json")
    assert rows == [
        {
            "buyer": False,
            "commission": "0.02616201",
            "commissionAsset": "USDT",
            "id": 549733079,
            "maker": False,
            "marginAsset": "USDT",
            "orderId": 28645789207,
            "positionSide": "BOTH",
            "price": "81756.30",
            "qty": "0.0008",
            "quoteQty": "65.405040",
            "realizedPnl": "-0.00327999",
            "side": "SELL",
            "symbol": "BTCUSDT",
            "time": 1792670963058,
        }
    ]


def test_the_commission_case_rows_keep_the_recorded_order_and_types() -> None:
    rows = _json(RECORDED / "user_trades_commission_case.json")
    assert [row["id"] for row in rows] == [549732633, 549732634, 549732632]
    assert [row["realizedPnl"] for row in rows] == ["-0.00584999", "-0.00350999", "0"]
    assert all(isinstance(row["id"], int) and isinstance(row["time"], int) for row in rows)
    assert all(isinstance(row["buyer"], bool) and isinstance(row["maker"], bool) for row in rows)
    assert {row["symbol"] for row in rows} == {"BTCUSDT"}


def test_the_empty_funding_income_answer_is_an_empty_list() -> None:
    assert _json(RECORDED / "income_funding_empty.json") == []


def test_trade_rows_map_probe_fields_to_sdk_aliases_and_types() -> None:
    generator = _load_generator()
    summary = {
        "count": "1",
        "row_0_buyer": "true",
        "row_0_commission": "1",
        "row_0_commission_asset": "USDT",
        "row_0_maker": "false",
        "row_0_margin_asset": "USDT",
        "row_0_order_id": "5",
        "row_0_position_side": "BOTH",
        "row_0_price": "2",
        "row_0_qty": "3",
        "row_0_quote_qty": "6",
        "row_0_realized_pnl": "0",
        "row_0_side": "BUY",
        "row_0_time_ms": "9",
        "row_0_trade_id": "4",
    }
    (row,) = generator.trade_rows(summary)
    assert row["id"] == 4 and row["orderId"] == 5 and row["time"] == 9
    assert row["buyer"] is True and row["maker"] is False
    assert row["symbol"] == generator.TRADE_CASE_SYMBOL


@pytest.mark.parametrize(
    "mutation",
    [
        {"count": "2"},  # count disagrees with the rows
        {"row_0_unknown": "1"},  # unknown field
        {"row_0_time_ms": "1.5"},  # foreign text for an integer
        {"row_0_buyer": "yes"},  # foreign text for a bool
    ],
    ids=["count", "unknown_field", "bad_int", "bad_bool"],
)
def test_a_malformed_trade_summary_raises(mutation: dict[str, str]) -> None:
    generator = _load_generator()
    summary = {
        "count": "1",
        "row_0_buyer": "true",
        "row_0_commission": "1",
        "row_0_commission_asset": "USDT",
        "row_0_maker": "false",
        "row_0_margin_asset": "USDT",
        "row_0_order_id": "5",
        "row_0_position_side": "BOTH",
        "row_0_price": "2",
        "row_0_qty": "3",
        "row_0_quote_qty": "6",
        "row_0_realized_pnl": "0",
        "row_0_side": "BUY",
        "row_0_time_ms": "9",
        "row_0_trade_id": "4",
        **mutation,
    }
    with pytest.raises(ValueError, match="recorded|buyer|time"):
        generator.trade_rows(summary)


def test_every_recorded_stream_frame_is_a_byte_copy_of_its_source() -> None:
    copies = sorted(FRAMES.glob("*.json"))
    assert copies, "no frame was copied"
    names = {path.name for path in copies}
    assert "triggered_close_position_bracket-010-ORDER_TRADE_UPDATE.json" in names
    assert "triggered_close_position_bracket-009-ACCOUNT_UPDATE.json" in names
    for copy in copies:
        source = PHASE19_FIXTURES / copy.name
        assert copy.read_bytes() == source.read_bytes(), copy.name
        assert _json(copy) == _json(source), copy.name
        assert copy.name.split("-")[0] in {
            "triggered_close_position_bracket",
            "commission_vs_realized_pnl",
        }
        assert "ORDER_TRADE_UPDATE" in copy.name or "ACCOUNT_UPDATE" in copy.name


def test_the_copied_frames_are_exactly_the_order_and_account_frames_of_the_two_cases() -> None:
    expected = {
        path.name
        for path in PHASE19_FIXTURES.glob("*.json")
        if path.name.startswith(
            ("triggered_close_position_bracket-0", "commission_vs_realized_pnl-0")
        )
        and ("-ORDER_TRADE_UPDATE" in path.name or "-ACCOUNT_UPDATE" in path.name)
    }
    assert {path.name for path in FRAMES.glob("*.json")} == expected
    assert len(expected) == 20


def test_the_triggered_close_frame_carries_the_rest_row_keys() -> None:
    frame = _json(FRAMES / "triggered_close_position_bracket-010-ORDER_TRADE_UPDATE.json")
    order = frame["o"]
    assert order["i"] == 28645789207 and order["t"] == 549733079
    assert order["rp"] == "-0.00327999" and order["n"] == "0.02616201" and order["N"] == "USDT"


def test_a_fresh_run_writes_the_same_frames_and_trade_files(tmp_path: Path) -> None:
    generator = _load_generator()
    assert generator.main(["--out", str(tmp_path)]) == 0
    fresh = tmp_path / "recorded_demo"
    for name in ("user_trades_commission_case.json", "user_trades_triggered_bracket.json"):
        assert _json(RECORDED / name) == _json(fresh / name)
        assert (RECORDED / name).read_text(encoding="utf-8") == (fresh / name).read_text(
            encoding="utf-8"
        ).replace("\r\n", "\n")
    assert _json(RECORDED / "income_funding_empty.json") == _json(
        fresh / "income_funding_empty.json"
    )
    assert _snapshot(FRAMES) == _snapshot(fresh / "frames")
