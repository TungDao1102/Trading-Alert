"""Tests for scripts/geometry_census.py (Phase 15, plan 15-07, D-11, D-17, F8).

The census core is exercised on the hand-derived windows of plans 15-03..15-06 and the CLI on
a tiny synthetic store published through the real writers. Nothing here touches the network,
a database or the real data store.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from scripts import geometry_census as census
from src.adapters.binance_usdm import Kline
from src.core.planner import plan
from src.core.strategy import evaluate
from src.core.types import AccountState, Candle, MarketSnapshot
from src.data.store import publish_batch
from src.domain.trade_plan import TradePlan

from tests import geometry_builders
from tests.test_planner_geometry import _case_set

EQUITY = Decimal("1000")


def _long_plan() -> TradePlan:
    """The a_long_worked plan: zone 97.80..100.20, stop 97.40, TP1 106.00."""
    parameter_set = _case_set("a_long_worked")
    setup, context = geometry_builders.family_a_long_window()
    result = evaluate(
        snapshot=MarketSnapshot(
            symbol="BTCUSDT", setup_candles=setup, context_candles=context, source_timeframe="1h"
        ),
        account_state=AccountState(equity=EQUITY, risk_rate=Decimal("0.005")),
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    assert result.signal is not None
    planned = plan(
        signal=result.signal,
        setup_candles=setup,
        parameter_set=parameter_set,
        account_state=AccountState(equity=EQUITY, risk_rate=Decimal("0.005")),
        created_at_utc=setup[-1].close_time_utc,
    )
    assert planned.trade_plan is not None
    return planned.trade_plan


def _with(trade_plan: TradePlan, **changes: Any) -> TradePlan:
    return dataclasses.replace(trade_plan, **changes)


def _tp(tp1: str) -> str:
    return json.dumps({"tp1": tp1, "tp2": "999", "tp1_role": "TAKE_PROFIT_1"}, sort_keys=True)


# --------------------------------------------------------------------------- #
# geometry_violations: the independent invariant checker (F8)
# --------------------------------------------------------------------------- #


def test_valid_long_plan_has_no_violations() -> None:
    assert census.geometry_violations(_long_plan(), "LONG") == []


def test_long_stop_inside_zone_is_named() -> None:
    base = _long_plan()
    broken = _with(base, stop_loss_price=Decimal("98.50"))  # zone starts at 97.80
    assert "stop_inside_zone" in census.geometry_violations(broken, "LONG")


def test_long_stop_equal_to_zone_edge_is_a_violation() -> None:
    base = _long_plan()
    broken = _with(base, stop_loss_price=base.entry_min_price)
    assert "stop_inside_zone" in census.geometry_violations(broken, "LONG")


def test_long_tp1_on_the_loss_side_is_named() -> None:
    broken = _with(_long_plan(), take_profit_json=_tp("90"))
    assert "tp1_loss_side" in census.geometry_violations(broken, "LONG")


def test_long_tp1_equal_to_entry_ref_is_a_violation() -> None:
    base = _long_plan()
    entry_ref = (base.entry_min_price + base.entry_max_price) / 2
    broken = _with(base, take_profit_json=_tp(str(entry_ref)))
    assert "tp1_loss_side" in census.geometry_violations(broken, "LONG")


def test_short_checks_are_mirrored() -> None:
    base = _long_plan()  # zone 97.80..100.20
    # SHORT: stop must be above entry_max and TP1 below entry_ref.
    ok = _with(base, stop_loss_price=Decimal("101"), take_profit_json=_tp("90"))
    assert census.geometry_violations(ok, "SHORT") == []
    inside = _with(base, stop_loss_price=Decimal("99"), take_profit_json=_tp("90"))
    assert "stop_inside_zone" in census.geometry_violations(inside, "SHORT")
    loss_side = _with(base, stop_loss_price=Decimal("101"), take_profit_json=_tp("120"))
    assert "tp1_loss_side" in census.geometry_violations(loss_side, "SHORT")


def test_unparseable_take_profit_is_a_violation_not_a_crash() -> None:
    broken = _with(_long_plan(), take_profit_json="not json")
    assert "tp1_unreadable" in census.geometry_violations(broken, "LONG")


def test_unknown_direction_is_refused() -> None:
    with pytest.raises(ValueError):
        census.geometry_violations(_long_plan(), "SIDEWAYS")


def test_inverted_zone_is_named() -> None:
    base = _long_plan()
    broken = _with(base, entry_min_price=Decimal("101"), entry_max_price=Decimal("100"))
    assert "zone_inverted" in census.geometry_violations(broken, "LONG")


# --------------------------------------------------------------------------- #
# census_window: counts through the real public functions
# --------------------------------------------------------------------------- #


def _last_index(setup: list[Candle]) -> list[int]:
    return [len(setup) - 1]


def test_census_window_counts_the_worked_long_setup_and_plan() -> None:
    setup, context = geometry_builders.family_a_long_window()
    counts = census.census_window(
        setup_bars=setup,
        context_bars=context,
        indices=_last_index(setup),
        parameter_set=_case_set("a_long_worked"),
        equity=EQUITY,
    )
    assert counts.bars_evaluated == 1
    assert counts.setups == 1
    assert counts.plans == 1
    assert counts.invariant_violations == 0
    assert counts.guard_pass == 1
    assert counts.guard_reject == {}
    assert counts.by_direction["LONG"]["setups"] == 1
    assert counts.by_direction["LONG"]["plans"] == 1


def test_census_window_counts_strategy_no_trade_reasons() -> None:
    setup, context = geometry_builders.family_a_long_window()
    counts = census.census_window(
        setup_bars=setup,
        context_bars=context,
        indices=[100, 120],
        parameter_set=_case_set("a_long_worked"),
        equity=EQUITY,
    )
    assert counts.bars_evaluated == 2
    assert counts.setups + sum(counts.strategy_no_trade.values()) == 2


def test_census_window_counts_the_stop_too_tight_guard() -> None:
    setup, context = geometry_builders.family_a_long_window()
    # The worked plan has a stop distance rate of about 2.8 percent; a 4 percent floor rejects it.
    parameter_set = _case_set("a_long_worked", min_stop_distance_rate="0.04")
    counts = census.census_window(
        setup_bars=setup,
        context_bars=context,
        indices=_last_index(setup),
        parameter_set=parameter_set,
        equity=EQUITY,
    )
    assert counts.plans == 1
    assert counts.guard_reject == {"STOP_TOO_TIGHT": 1}
    assert counts.guard_pass == 0


def test_census_window_counts_the_cost_to_risk_guard() -> None:
    setup, context = geometry_builders.family_a_long_window()
    # Cost-to-risk of the worked plan is about 0.047; a ceiling of 0.01 rejects it.
    parameter_set = _case_set("a_long_worked", max_cost_to_risk="0.01")
    counts = census.census_window(
        setup_bars=setup,
        context_bars=context,
        indices=_last_index(setup),
        parameter_set=parameter_set,
        equity=EQUITY,
    )
    assert counts.guard_reject == {"COST_TO_RISK_EXCEEDED": 1}


def test_census_window_counts_planner_no_trade_reasons() -> None:
    setup, context = geometry_builders.range_mr_narrow_window()
    parameter_set = _range_mr_set()
    counts = census.census_window(
        setup_bars=setup,
        context_bars=context,
        indices=_last_index(setup),
        parameter_set=parameter_set,
        equity=EQUITY,
    )
    # The narrow range with T_MID is the RR gate case of plan 15-06.
    assert counts.setups == 1
    assert counts.plans == 0
    assert counts.planner_no_trade == {"RR_TOO_LOW": 1}


def _range_mr_set() -> Any:
    return _case_set("c_long_worked")


def test_census_window_counts_a_violation_the_checker_finds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup, context = geometry_builders.family_a_long_window()
    monkeypatch.setattr(
        census, "geometry_violations", lambda plan_, direction: ["stop_inside_zone"]
    )
    counts = census.census_window(
        setup_bars=setup,
        context_bars=context,
        indices=_last_index(setup),
        parameter_set=_case_set("a_long_worked"),
        equity=EQUITY,
    )
    assert counts.invariant_violations == 1
    assert counts.violation_kinds == {"stop_inside_zone": 1}
    assert counts.by_direction["LONG"]["invariant_violations"] == 1


def test_census_window_is_deterministic() -> None:
    setup, context = geometry_builders.family_a_long_window()
    kwargs: dict[str, Any] = {
        "setup_bars": setup,
        "context_bars": context,
        "indices": [100, 200, 249],
        "parameter_set": _case_set("a_long_worked"),
        "equity": EQUITY,
    }
    first = census.census_window(**kwargs).to_dict()
    second = census.census_window(**kwargs).to_dict()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_counts_merge_adds_every_counter() -> None:
    setup, context = geometry_builders.family_a_long_window()
    one = census.census_window(
        setup_bars=setup,
        context_bars=context,
        indices=_last_index(setup),
        parameter_set=_case_set("a_long_worked"),
        equity=EQUITY,
    )
    total = census.CensusCounts()
    total.merge(one)
    total.merge(one)
    assert total.bars_evaluated == 2
    assert total.plans == 2
    assert total.guard_pass == 2
    assert total.by_direction["LONG"]["plans"] == 2


def test_the_census_reports_no_outcome_fields() -> None:
    """D-17: counts only. No PnL, fill, exit or trade outcome key may exist."""
    keys = set(census.CensusCounts().to_dict())
    for forbidden in ("pnl", "profit", "fill", "exit", "win", "outcome", "return"):
        assert not any(forbidden in key for key in keys)


def test_the_checker_does_not_reuse_the_planner_validator() -> None:
    """F8: a checker that imports the validator cannot catch a validator defect."""
    source = Path(census.__file__).read_text(encoding="utf-8")
    assert "_geometry_rejection" not in source


def test_exit_code_is_one_when_a_violation_was_counted() -> None:
    clean = census.CensusCounts()
    dirty = census.CensusCounts(invariant_violations=1)
    assert census.exit_code_for(clean) == census.EXIT_OK
    assert census.exit_code_for(dirty) == census.EXIT_VIOLATION


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

SYMBOL = "BTCUSDT"
START = datetime(2026, 7, 1, tzinfo=UTC)
END = datetime(2026, 7, 3, tzinfo=UTC)  # exclusive: two whole UTC days
_STEP = {"1h": timedelta(hours=1), "4h": timedelta(hours=4)}


def _kline(interval: str, open_time: datetime, wave: int) -> Kline:
    price = Decimal(100) + Decimal(wave % 7)
    return Kline(
        symbol=SYMBOL,
        interval=interval,
        open_time_utc=open_time,
        close_time_utc=open_time + _STEP[interval] - timedelta(milliseconds=1),
        open=price,
        high=price + Decimal("0.5"),
        low=price - Decimal("0.5"),
        close=price,
        volume=Decimal("1.5"),
        quote_volume=price * Decimal("1.5"),
        trade_count=7,
    )


@pytest.fixture(scope="module")
def raw_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("census_store") / "raw"
    for interval, step in _STEP.items():
        rows = []
        moment = START
        index = 0
        while moment < END:
            rows.append(_kline(interval, moment, index))
            moment += step
            index += 1
        publish_batch(rows, interval=interval, symbol=SYMBOL, raw_root=root)
    return root


def _args(raw_root: Path, *extra: str) -> list[str]:
    return [
        "--symbols",
        SYMBOL,
        "--days",
        "2",
        "--end-day",
        "2026-07-02",
        "--warmup-days",
        "0",
        "--raw-root",
        str(raw_root),
        *extra,
    ]


def test_missing_end_day_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert census.main(["--symbols", SYMBOL, "--days", "2"]) == census.EXIT_USAGE


def test_missing_symbols_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert census.main(["--days", "2", "--end-day", "2026-07-02"]) == census.EXIT_USAGE


def test_unknown_strategy_id_exits_2_without_a_traceback(
    raw_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = census.main(_args(raw_root, "--strategy-id", "no-such-strategy"))
    assert code in (census.EXIT_USAGE, census.EXIT_FAILURE)
    assert "Traceback" not in capsys.readouterr().err


def test_bad_symbol_exits_2(raw_root: Path) -> None:
    args = _args(raw_root)
    args[args.index(SYMBOL)] = "btc-usdt"
    assert census.main(args) == census.EXIT_USAGE


def test_bad_end_day_exits_2(raw_root: Path) -> None:
    args = _args(raw_root)
    args[args.index("2026-07-02")] = "yesterday"
    assert census.main(args) == census.EXIT_USAGE


def test_stride_below_one_exits_2(raw_root: Path) -> None:
    assert census.main(_args(raw_root, "--stride", "0")) == census.EXIT_USAGE


def test_cli_prints_sorted_json_lines_and_a_total(
    raw_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = census.main(_args(raw_root))
    out = capsys.readouterr().out.strip().splitlines()
    assert code == census.EXIT_OK
    assert len(out) == 2  # one symbol line and one total line
    for line in out:
        parsed = json.loads(line)
        assert json.dumps(parsed, sort_keys=True) == line
    symbol_line, total_line = (json.loads(line) for line in out)
    assert symbol_line["kind"] == "symbol"
    assert symbol_line["symbol"] == SYMBOL
    assert total_line["kind"] == "total"
    # 2 days of 1h bars, every closed bar evaluated.
    assert symbol_line["bars_evaluated"] == 48
    assert total_line["bars_evaluated"] == 48
    assert total_line["invariant_violations"] == 0


def test_cli_stride_thins_the_evaluated_bars(
    raw_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert census.main(_args(raw_root, "--stride", "2")) == census.EXIT_OK
    symbol_line = json.loads(capsys.readouterr().out.strip().splitlines()[0])
    assert symbol_line["bars_evaluated"] == 24
    assert symbol_line["stride"] == 2


def test_cli_reads_a_scratch_registry_root_and_restores_the_default(
    raw_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from src.domain import registry

    default_root = registry.REGISTRY_ROOT
    scratch = tmp_path / "registry"
    (scratch / "trend-pullback").mkdir(parents=True)
    source = (default_root / "trend-pullback" / "baseline-v5.toml").read_text(encoding="utf-8")
    (scratch / "trend-pullback" / "scratch-v1.toml").write_text(source, encoding="utf-8")
    code = census.main(
        _args(
            raw_root,
            "--registry-root",
            str(scratch),
            "--parameter-set-id",
            "scratch-v1",
        )
    )
    assert code == census.EXIT_OK
    assert registry.REGISTRY_ROOT == default_root
    assert json.loads(capsys.readouterr().out.strip().splitlines()[0])["parameter_set_id"] == (
        "scratch-v1"
    )
