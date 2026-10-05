"""Simulator-level determinism suites for the v2 engine (Phase 14, plan 14-09, Task 3; F-602).

Until now rerun, prefix-invariance and no-lookahead suites existed only for
`strategy.evaluate`. These prove the same properties for `engine.simulate` on a multi-symbol
scripted case and on the 250-bar phase 6 strategy case:

- rerun: two runs give byte-identical output (sha256 over canonical JSON);
- shuffle: strategy, context, funding, constraint and scripted rows in a fixed-seed random
  order give the identical output (minute rows are a time-ordered source and are never
  shuffled);
- prefix invariance (D-34): cutting the data at a time X inside the run (bars, plans, minutes
  and funding after X removed) leaves every terminal record of the prefix byte-identical in
  the extended run. The exclusion is exactly the records the data end itself resolves: a
  record whose `entry_kind` is PENDING_AT_DATA_END or whose `exit_kind` is END_OF_DATA ends
  because the data ended, so it legitimately differs once more data exists;
- 1m no-lookahead: appending minutes after the last minute of the prefix, or replacing every
  minute after a record's resolution with seeded noise, never changes a record that was
  already terminal;
- window equivalence (D-31): a window larger than the case gives the same output as the
  default windows on the 250-bar strategy case.
"""

from __future__ import annotations

import copy
import hashlib
import json
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from src.backtest import engine
from src.backtest.engine import simulate
from src.domain.enums import DailyState
from src.risk.gating import evaluate_risk
from src.risk.types import PortfolioVerdict

from tests.backtest_case_helpers import (
    SIGNAL_CLOSE,
    at,
    fixed_risk_fn,
    make_case,
    minute_close,
    minute_row,
    scripted_plan,
)
from tests.test_backtest_engine_strategy import trigger_case

NEXT_CLOSE = SIGNAL_CLOSE + timedelta(hours=1)  # 10:59:59.999
LATE_CLOSE = SIGNAL_CLOSE + timedelta(hours=3)  # 12:59:59.999
SYMBOLS = ("ADAUSDT", "BTCUSDT", "ETHUSDT", "LTCUSDT", "SOLUSDT")
CUT = at(11, 45)  # the prefix ends here; the extended run goes on to 14:00
FULL_END = at(14, 0)


def digest(output: dict[str, Any]) -> str:
    """sha256 over the canonical JSON of an engine output."""
    text = json.dumps(output, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def minute_rows(
    symbol: str,
    kind: str,
    price: str,
    end: datetime,
    overrides: dict[datetime, dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Flat 1m rows from 10:00 up to (not including) `end`, with per-minute overrides."""
    rows: list[dict[str, str]] = []
    moment = at(10, 0)
    centre = Decimal(price)
    half = Decimal("0.05")
    while moment < end:
        override = (overrides or {}).get(moment)
        rows.append(
            override
            if override is not None
            else minute_row(
                symbol,
                moment,
                str(centre),
                str(centre + half),
                str(centre - half),
                str(centre),
                kind=kind,  # type: ignore[arg-type]
            )
        )
        moment += timedelta(minutes=1)
    return rows


def go_row(symbol: str, when: datetime) -> dict[str, str]:
    return minute_row(symbol, when, "100.20", "100.30", "99.80", "100.00", kind="trade")


def stop_row(symbol: str, when: datetime) -> dict[str, str]:
    return minute_row(symbol, when, "98.50", "98.60", "97.90", "98.20", kind="mark")


def scripted_case(data_end: datetime) -> dict[str, Any]:
    """Five symbols: BTC and SOL stop out, ETH fills and stays open, ADA rests and expires.

    Plans: ADA (2 h expiry), BTC, ETH and LTC at 09:59:59.999, SOL at 10:59:59.999, and a
    second SOL plan at 12:59:59.999 that only exists when the data reaches it. With
    `capped_risk_fn` (at most three open or resting entries) the fourth setup of the first
    close, in (time, symbol) order, is LTC and is rejected: a different processing order would
    reject another symbol, so the output depends on the engine's ordering rule. Only data at
    or before `data_end` is included, so `scripted_case(CUT)` is the prefix of
    `scripted_case(FULL_END)`.
    """
    trade_overrides = {
        "BTCUSDT": {at(10, 1): go_row("BTCUSDT", at(10, 1))},
        "ETHUSDT": {at(11, 20): go_row("ETHUSDT", at(11, 20))},
        "SOLUSDT": {
            at(11, 1): go_row("SOLUSDT", at(11, 1)),
            at(13, 1): go_row("SOLUSDT", at(13, 1)),
        },
        "ADAUSDT": {},
        "LTCUSDT": {},
    }
    mark_overrides = {
        "BTCUSDT": {at(10, 40): stop_row("BTCUSDT", at(10, 40))},
        "SOLUSDT": {at(11, 30): stop_row("SOLUSDT", at(11, 30))},
    }
    trades: list[dict[str, str]] = []
    marks: list[dict[str, str]] = []
    for symbol in SYMBOLS:
        trades += minute_rows(symbol, "trade", "105.00", data_end, trade_overrides[symbol])
        marks += minute_rows(symbol, "mark", "100.00", data_end, mark_overrides.get(symbol))
    plans = [
        scripted_plan("BTCUSDT", SIGNAL_CLOSE, "sig-btc"),
        scripted_plan("ETHUSDT", SIGNAL_CLOSE, "sig-eth", regime="BULLISH"),
        scripted_plan("SOLUSDT", NEXT_CLOSE, "sig-sol-1"),
        scripted_plan("ADAUSDT", SIGNAL_CLOSE, "sig-ada", expiry_hours=2),
        scripted_plan("LTCUSDT", SIGNAL_CLOSE, "sig-ltc"),
        scripted_plan("SOLUSDT", LATE_CLOSE, "sig-sol-2"),
    ]
    plans = [p for p in plans if datetime.fromisoformat(p["bar_close_utc"]) <= data_end]
    funding_instants = [
        datetime(2026, 1, 4, 16, 0, tzinfo=UTC),
        datetime(2026, 1, 5, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 5, 8, 0, tzinfo=UTC),
        datetime(2026, 1, 5, 16, 0, tzinfo=UTC),
        datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
    ]
    funding = [
        {
            "symbol": symbol,
            "funding_time_utc": when.isoformat(),
            "funding_rate": "0.0001",
            "mark_price": "100",
        }
        for symbol in SYMBOLS
        for when in funding_instants
    ]
    return make_case(
        symbols=SYMBOLS,
        scripted=plans,
        trade_minutes=trades,
        mark_minutes=marks,
        funding=funding,
        data_end=data_end,
    )


def capped_risk_fn() -> Any:
    """`fixed_risk_fn` that refuses a fourth open or resting entry (order-sensitive on purpose)."""
    inner = fixed_risk_fn("0.5", "1.50")

    def risk_fn(**kwargs: Any) -> PortfolioVerdict:
        if len(kwargs["open_positions"]) >= 3:
            return PortfolioVerdict(
                is_no_trade=True,
                sized=None,
                reason_code="MAX_POSITIONS_REJECT",
                daily_state=DailyState.NORMAL,
            )
        return inner(**kwargs)

    return risk_fn


def scripted_run(data_end: datetime) -> dict[str, Any]:
    return simulate(scripted_case(data_end), risk_fn=capped_risk_fn())


def strategy_run(case: dict[str, Any]) -> dict[str, Any]:
    return simulate(case, risk_fn=evaluate_risk)


def shuffled(case: dict[str, Any], seed: int) -> dict[str, Any]:
    """The same case with every row family that is a set in meaning in a seeded random order.

    Minute rows are excluded on purpose: they are a time-ordered source, not a set.
    """
    rng = random.Random(seed)
    other = copy.deepcopy(case)
    for key in (
        "strategy_bars",
        "context_bars",
        "funding",
        "constraint_history",
        "scripted_plans",
        "symbols",
    ):
        if key in other:
            rng.shuffle(other[key])
    return other


def by_id(output: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {t["trade_id"]: t for t in output["trades"]}


def is_data_end_record(record: dict[str, Any]) -> bool:
    return record["entry_kind"] == "PENDING_AT_DATA_END" or record["exit_kind"] == "END_OF_DATA"


def terminal_before_end(output: dict[str, Any]) -> list[dict[str, Any]]:
    """Records the data end did not resolve (D-34 exclusion: END_OF_DATA, PENDING_AT_DATA_END)."""
    return [t for t in output["trades"] if not is_data_end_record(t)]


# --------------------------------------------------------------------------- #
# rerun
# --------------------------------------------------------------------------- #


def test_two_runs_of_the_multi_symbol_scripted_case_are_byte_identical() -> None:
    first, second = scripted_run(FULL_END), scripted_run(FULL_END)

    assert digest(first) == digest(second)
    assert len(first["trades"]) == 6


def test_two_runs_of_the_phase_6_strategy_case_are_byte_identical() -> None:
    case, _, _ = trigger_case()

    assert digest(strategy_run(case)) == digest(strategy_run(copy.deepcopy(case)))


# --------------------------------------------------------------------------- #
# shuffle
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("seed", [1, 20260105, 99])
def test_shuffled_scripted_rows_give_the_identical_output(seed: int) -> None:
    case = scripted_case(FULL_END)
    risk_fn = capped_risk_fn()

    assert digest(simulate(shuffled(case, seed), risk_fn=risk_fn)) == digest(
        simulate(case, risk_fn=risk_fn)
    )


@pytest.mark.parametrize("seed", [3, 7])
def test_shuffled_strategy_and_context_rows_give_the_identical_output(seed: int) -> None:
    case, _, _ = trigger_case()

    assert digest(strategy_run(shuffled(case, seed))) == digest(strategy_run(case))


# --------------------------------------------------------------------------- #
# prefix invariance (D-34)
# --------------------------------------------------------------------------- #


def test_every_terminal_prefix_record_is_byte_identical_in_the_extended_run() -> None:
    """D-34: the exclusion is the records the data end itself resolved (END_OF_DATA,
    PENDING_AT_DATA_END); everything the prefix settled before X must not move."""
    prefix, extended = scripted_run(CUT), scripted_run(FULL_END)
    extended_by_id = by_id(extended)

    settled = terminal_before_end(prefix)
    assert {t["signal_id"] for t in settled} == {"sig-btc", "sig-sol-1", "sig-ltc"}
    for record in settled:
        assert extended_by_id[record["trade_id"]] == record


def test_the_data_end_records_of_the_prefix_are_the_ones_that_move() -> None:
    # Non-vacuity: the exclusion is exactly the set that changes once more data exists.
    prefix, extended = scripted_run(CUT), scripted_run(FULL_END)
    prefix_open = [t for t in prefix["trades"] if is_data_end_record(t)]
    extended_by_signal = {t["signal_id"]: t for t in extended["trades"]}

    assert {t["signal_id"] for t in prefix_open} == {"sig-eth", "sig-ada"}
    assert {t["signal_id"]: t["entry_kind"] for t in prefix_open}["sig-ada"] == (
        "PENDING_AT_DATA_END"
    )
    assert extended_by_signal["sig-ada"]["entry_kind"] == "EXPIRED"
    eth_prefix = next(t for t in prefix_open if t["signal_id"] == "sig-eth")
    assert eth_prefix["exit_kind"] == "END_OF_DATA"
    assert extended_by_signal["sig-eth"]["exit_time_utc"] != eth_prefix["exit_time_utc"]


def test_the_phase_6_prefix_record_is_unchanged_when_the_data_window_is_extended() -> None:
    case, _, _ = trigger_case()
    prefix = strategy_run(case)
    longer = copy.deepcopy(case)
    end = datetime.fromisoformat(case["data_window"]["end_utc"])
    longer["data_window"]["end_utc"] = (end + timedelta(hours=2)).isoformat()
    longer["funding"].append(
        {
            "symbol": "BTCUSDT",
            "funding_time_utc": (end + timedelta(hours=2)).isoformat(),
            "funding_rate": "0",
            "mark_price": "100",
        }
    )
    extended = strategy_run(longer)
    extended_by_id = by_id(extended)

    settled = terminal_before_end(prefix)
    assert len(settled) == 1
    assert extended_by_id[settled[0]["trade_id"]] == settled[0]


# --------------------------------------------------------------------------- #
# 1m no-lookahead
# --------------------------------------------------------------------------- #


def test_minutes_appended_after_the_prefix_never_change_a_settled_record() -> None:
    prefix = scripted_run(CUT)
    # The extended case is the prefix case with 135 more minutes per symbol and series.
    extended = scripted_run(FULL_END)
    extended_by_id = by_id(extended)

    settled = terminal_before_end(prefix)
    assert settled, "the prefix must settle at least one record"
    for record in settled:
        assert extended_by_id[record["trade_id"]] == record


def noise_rows(symbol: str, kind: str, after: datetime, end: datetime, seed: int) -> list[Any]:
    """Valid but arbitrary 1m rows (seeded) from `after` up to `end`."""
    rng = random.Random(seed)
    rows = []
    moment = after
    while moment < end:
        base = Decimal(rng.randint(50, 150))
        spread = Decimal(rng.randint(0, 40)) / Decimal(10)
        rows.append(
            minute_row(
                symbol,
                moment,
                str(base),
                str(base + spread),
                str(base - spread),
                str(base),
                kind=kind,
            )
        )
        moment += timedelta(minutes=1)
    return rows


@pytest.mark.parametrize("seed", [11, 12, 13])
def test_noise_after_a_records_resolution_never_changes_that_record(seed: int) -> None:
    base_case = scripted_case(FULL_END)
    baseline = {t["signal_id"]: t for t in simulate(base_case, risk_fn=capped_risk_fn())["trades"]}
    btc = baseline["sig-btc"]
    assert btc["exit_kind"] == "SL"
    resolved = datetime.fromisoformat(btc["resolved_at_utc"])
    first_after = minute_close(at(10, 40)).replace(second=0, microsecond=0) + timedelta(minutes=1)
    assert first_after > resolved - timedelta(minutes=1)

    noisy = copy.deepcopy(base_case)
    kept_trade = [
        r
        for r in noisy["trade_bars_1m"]
        if not (
            r["symbol"] == "BTCUSDT" and datetime.fromisoformat(r["open_time_utc"]) >= first_after
        )
    ]
    kept_mark = [
        r
        for r in noisy["mark_bars_1m"]
        if not (
            r["symbol"] == "BTCUSDT" and datetime.fromisoformat(r["open_time_utc"]) >= first_after
        )
    ]
    noisy["trade_bars_1m"] = kept_trade + noise_rows(
        "BTCUSDT", "trade", first_after, FULL_END, seed
    )
    noisy["mark_bars_1m"] = kept_mark + noise_rows(
        "BTCUSDT", "mark", first_after, FULL_END, seed + 1
    )
    out = {t["signal_id"]: t for t in simulate(noisy, risk_fn=capped_risk_fn())["trades"]}

    assert out["sig-btc"] == btc


def test_minutes_after_the_data_end_are_never_read() -> None:
    case = scripted_case(CUT)
    padded = copy.deepcopy(case)
    for symbol in SYMBOLS:
        padded["trade_bars_1m"] += noise_rows(symbol, "trade", CUT, FULL_END, 5)
        padded["mark_bars_1m"] += noise_rows(symbol, "mark", CUT, FULL_END, 6)
    risk_fn = capped_risk_fn()

    assert digest(simulate(padded, risk_fn=risk_fn)) == digest(simulate(case, risk_fn=risk_fn))


# --------------------------------------------------------------------------- #
# window equivalence (D-31)
# --------------------------------------------------------------------------- #


def test_a_window_larger_than_the_case_equals_the_default_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case, _, _ = trigger_case()
    default = strategy_run(case)

    monkeypatch.setattr(engine, "STRATEGY_WINDOW_BARS", 100_000)
    monkeypatch.setattr(engine, "CONTEXT_WINDOW_BARS", 100_000)
    unwindowed = strategy_run(copy.deepcopy(case))

    assert len(default["trades"]) == 1
    # The summary reports the window sizes in force, so it differs by design in those two
    # keys; every other fact, and every record, is identical.
    assert unwindowed["trades"] == default["trades"]
    for key in ("strategy_window_bars", "context_window_bars"):
        assert unwindowed["run_summary"].pop(key) == 100_000
        assert default["run_summary"].pop(key) in (1000, 300)
    assert unwindowed == default
